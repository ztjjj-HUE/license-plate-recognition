from dataclasses import dataclass;import json,struct;from typing import List,Optional;import zlib;from shared.lpr_wire import Packet,PacketKind,encode_packet;MAX_WIDTH=640;MAX_HEIGHT=480;MAX_IMAGE_BYTES=MAX_WIDTH*MAX_HEIGHT;CHUNK_BYTES=32768;_OFFSET=struct.Struct('<I')
@dataclass(frozen=True)
class UploadEvent:stage:str;code:str;frame_id:int;image:Optional[bytes]=None;width:int=0;height:int=0
def encode_upload(frame_id:int,image:bytes,width:int,height:int,seq_start:int)->List[bytes]:
	if not isinstance(width,int)or not isinstance(height,int)or isinstance(width,bool)or isinstance(height,bool)or not 0<width<=MAX_WIDTH or not 0<height<=MAX_HEIGHT:raise ValueError('image dimensions exceed the static upload limit')
	if not isinstance(image,bytes)or len(image)!=width*height:raise ValueError('GRAY8 byte count must equal width * height')
	if not isinstance(frame_id,int)or not 0<=frame_id<=4294967295:raise ValueError('invalid frame_id')
	if not isinstance(seq_start,int)or not 0<=seq_start<=4294967295:raise ValueError('invalid seq_start')
	meta={'width':width,'height':height,'pixel_format':'gray8','total_bytes':len(image),'total_crc32':zlib.crc32(image)&4294967295,'chunk_bytes':CHUNK_BYTES};payload=json.dumps(meta,separators=(',',':'),sort_keys=True).encode('utf-8');A=seq_start;B=[encode_packet(PacketKind.IMAGE_BEGIN,A,frame_id,payload)]
	for offset in range(0,len(image),CHUNK_BYTES):A=A+1&4294967295;B.append(encode_packet(PacketKind.IMAGE_CHUNK,A,frame_id,_OFFSET.pack(offset)+image[offset:offset+CHUNK_BYTES]))
	A=A+1&4294967295;B.append(encode_packet(PacketKind.IMAGE_END,A,frame_id,b''));return B
class ImageAssembler:
	def __init__(self):self._reset()
	def _reset(self):self._frame_id=None;self._width=0;self._height=0;self._total=0;self._crc32=0;self._chunk_bytes=0;self._pixels=bytearray()
	def _error(self,code,frame_id):self._reset();return UploadEvent('error',code,frame_id)
	def accept(self,packet:Packet)->UploadEvent:
		frame_id=packet.frame_id
		if packet.kind==PacketKind.IMAGE_BEGIN:
			self._reset()
			try:meta=json.loads(packet.payload.decode('utf-8'));width=meta['width'];height=meta['height'];A=meta['total_bytes'];B=meta['total_crc32'];C=meta['chunk_bytes'];E=isinstance(width,int)and not isinstance(width,bool)and isinstance(height,int)and not isinstance(height,bool)and 0<width<=MAX_WIDTH and 0<height<=MAX_HEIGHT and meta['pixel_format']=='gray8'and isinstance(A,int)and A==width*height and isinstance(B,int)and 0<=B<=4294967295 and isinstance(C,int)and 0<C<=CHUNK_BYTES
			except(ValueError,TypeError,KeyError,UnicodeError):E=False
			if not E:return self._error('BAD_BEGIN',frame_id)
			self._frame_id=frame_id;self._width=width;self._height=height;self._total=A;self._crc32=B;self._chunk_bytes=C;return UploadEvent('ready','OK',frame_id)
		if self._frame_id is None:return UploadEvent('error','NO_TRANSFER',frame_id)
		if frame_id!=self._frame_id:return self._error('FRAME_MISMATCH',frame_id)
		if packet.kind==PacketKind.IMAGE_CHUNK:
			if len(packet.payload)<=_OFFSET.size:return self._error('BAD_CHUNK',frame_id)
			offset=_OFFSET.unpack_from(packet.payload)[0];D=packet.payload[_OFFSET.size:]
			if offset!=len(self._pixels):return self._error('BAD_OFFSET',frame_id)
			if len(D)>self._chunk_bytes or offset+len(D)>self._total:return self._error('BAD_CHUNK',frame_id)
			self._pixels.extend(D);return UploadEvent('chunk','OK',frame_id)
		if packet.kind==PacketKind.IMAGE_END:
			if packet.payload or len(self._pixels)!=self._total:return self._error('BAD_LENGTH',frame_id)
			if zlib.crc32(self._pixels)&4294967295!=self._crc32:return self._error('BAD_IMAGE_CRC',frame_id)
			result=UploadEvent('received','OK',frame_id,bytes(self._pixels),self._width,self._height);self._reset();return result
		return self._error('BAD_TYPE',frame_id)