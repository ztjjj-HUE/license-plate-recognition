import ctypes as ct,errno,mmap,os,select,time,numpy as np
class _Timeval(ct.Structure):_fields_=[('seconds',ct.c_ssize_t),('microseconds',ct.c_ssize_t)]
class _Memory(ct.Union):_fields_=[('offset',ct.c_uint32),('userptr',ct.c_size_t),('planes',ct.c_void_p),('fd',ct.c_int32)]
class _Plane(ct.Structure):_fields_=[('bytesused',ct.c_uint32),('length',ct.c_uint32),('m',_Memory),('data_offset',ct.c_uint32),('reserved',ct.c_uint32*11)]
class _Buffer(ct.Structure):_fields_=[('index',ct.c_uint32),('type',ct.c_uint32),('bytesused',ct.c_uint32),('flags',ct.c_uint32),('field',ct.c_uint32),('timestamp',_Timeval),('timecode',ct.c_uint8*16),('sequence',ct.c_uint32),('memory',ct.c_uint32),('m',_Memory),('length',ct.c_uint32),('reserved2',ct.c_uint32),('request_fd',ct.c_int32)]
class _FormatData(ct.Union):_fields_=[('raw',ct.c_uint8*200),('alignment',ct.c_void_p)]
class _Format(ct.Structure):_fields_=[('type',ct.c_uint32),('data',_FormatData)]
def _request(number,size,read=True,write=True):A=(2 if read else 0)|(1 if write else 0);return A<<30|size<<16|ord('V')<<8|number
def _ioctl(fd,number,obj,read=True,write=True):import fcntl;raw=bytearray(ct.string_at(ct.addressof(obj),ct.sizeof(obj)));fcntl.ioctl(fd,_request(number,len(raw),read,write),raw,True);ct.memmove(ct.addressof(obj),bytes(raw),len(raw))
def decode_bgr(raw,width,height,stride,bytesused,data_offset=0):
	if not(0<width<=1920 and 0<height<=1080):raise ValueError('unsupported DVP dimensions')
	if stride<width*3 or stride>16384 or data_offset<0:raise ValueError('invalid DVP stride/offset')
	A=(height-1)*stride+width*3
	if bytesused>len(raw)or bytesused<data_offset+A:raise ValueError('truncated DVP frame')
	B=np.ndarray((height,width,3),dtype=np.uint8,buffer=raw,offset=data_offset,strides=(stride,3,1));return B.copy()
class OV5640Capture:
	def __init__(self,device='/dev/video0',width=800,height=480,timeout=5):
		if os.name!='posix':raise OSError('OV5640 mmap capture requires Linux')
		if timeout<=0:raise ValueError('timeout must be positive')
		self.fd=-1;self.buffers=[];self.streaming=False;self.timeout=timeout
		try:
			self.fd=os.open(device,os.O_RDWR|os.O_NONBLOCK);D=(ct.c_uint8*104)();_ioctl(self.fd,0,D,write=False)
			if bytes(D)[16:48].split(b'\x00',1)[0]!=b'vcap_dvp output 0':raise ValueError('device is not the Qimingxing DVP capture node')
			A=_Format(type=9);import struct as B;B.pack_into('=IIII',A.data.raw,0,width,height,int.from_bytes(b'BGR3','little'),1);A.data.raw[180]=1;_ioctl(self.fd,5,A);self.width,self.height,F=B.unpack_from('=III',A.data.raw);self.sizeimage,self.stride=B.unpack_from('=II',A.data.raw,20)
			if(self.width,self.height,F)!=(width,height,int.from_bytes(b'BGR3','little')):raise ValueError('driver did not accept requested BGR dimensions')
			if not width*3<=self.stride<=16384 or not self.stride*height<=self.sizeimage<=32*1024*1024:raise ValueError('invalid driver frame layout')
			if A.data.raw[180]not in(0,1):raise ValueError('unexpected multi-plane layout')
			C=(ct.c_uint32*5)(3,9,1,0,0);_ioctl(self.fd,8,C)
			if not 1<=C[0]<=8:raise ValueError('invalid buffer count')
			for index in range(C[0]):
				plane=_Plane();E=self._buffer(index,plane);_ioctl(self.fd,9,E)
				if plane.length<self.sizeimage or plane.length>32*1024*1024:raise ValueError('invalid DMA buffer length')
				self.buffers.append(mmap.mmap(self.fd,plane.length,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE,offset=plane.m.offset));_ioctl(self.fd,15,E)
			_ioctl(self.fd,18,ct.c_int(9),read=False);self.streaming=True
		except BaseException:self.close();raise
	@staticmethod
	def _buffer(index,plane):return _Buffer(index=index,type=9,memory=1,m=_Memory(planes=ct.addressof(plane)),length=1)
	def read(self):
		if not self.streaming:raise OSError('DVP capture is closed')
		C=time.monotonic()+self.timeout
		while True:
			B=C-time.monotonic()
			if B<=0 or not select.select([self.fd],[],[],B)[0]:raise TimeoutError('OV5640 frame timeout')
			plane=_Plane();A=self._buffer(0,plane)
			try:_ioctl(self.fd,17,A)
			except OSError as D:
				if D.errno==errno.EAGAIN:continue
				raise
			if A.index>=len(self.buffers):raise ValueError('invalid dequeued buffer index')
			try:
				if A.flags&64:raise ValueError('V4L2 reports corrupted frame')
				frame=decode_bgr(self.buffers[A.index],self.width,self.height,self.stride,plane.bytesused,plane.data_offset);return A.sequence,frame
			finally:_ioctl(self.fd,15,A)
	def close(self):
		try:
			if self.streaming:
				try:_ioctl(self.fd,19,ct.c_int(9),read=False)
				finally:self.streaming=False
		finally:
			for A in self.buffers:A.close()
			self.buffers=[]
			if self.fd>=0:os.close(self.fd);self.fd=-1
	def __enter__(self):return self
	def __exit__(self,*args):self.close()