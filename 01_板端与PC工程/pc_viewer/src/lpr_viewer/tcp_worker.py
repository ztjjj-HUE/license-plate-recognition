from io import BytesIO;import ipaddress;from queue import Queue;import socket;from threading import Event,Thread;from PIL import Image;from pc_viewer.src.lpr_viewer.models import Detection,Frame;from pc_viewer.src.lpr_viewer.serial_worker import LatestFrameQueue;from shared.ethernet_wire import recv_frame
def connect_board(host,port,stop=None):
	if stop is not None and stop.is_set():raise OSError('connection cancelled')
	try:return socket.create_connection((host,port),timeout=3)
	except OSError as C:A=C
	try:D=ipaddress.ip_address(host)
	except ValueError:raise A
	if D.version!=4 or not D.is_link_local:raise A
	F=socket.getaddrinfo(socket.gethostname(),0,socket.AF_INET,socket.SOCK_STREAM);E=set()
	for G in F:
		B=G[4][0]
		if B in E or ipaddress.ip_address(B).is_loopback:continue
		E.add(B)
		if stop is not None and stop.is_set():raise OSError('connection cancelled')
		try:return socket.create_connection((host,port),timeout=1,source_address=(B,0))
		except OSError as C:A=C
	raise A
def decode_tcp_frame(meta,jpeg):
	with Image.open(BytesIO(jpeg))as image:size=image.size;image.verify()
	if size!=(meta['view_w'],meta['view_h']):raise ValueError('JPEG dimensions disagree with same-frame metadata')
	A=tuple(Detection(tuple(item['bbox_xyxy']),item['plate'],item['confidence_permille'])for item in meta['detections']);return Frame(meta['frame_id'],meta['capture_ms'],(meta['src_w'],meta['src_h']),(meta['view_w'],meta['view_h']),'jpeg',meta['state'],A,jpeg)
class TcpWorker:
	def __init__(self,host,port):self.host=host;self.port=int(port);self.frames=LatestFrameQueue();self.events=Queue();self.decode_errors=0;self._stop=Event();self._thread=None;self._socket=None
	def start(self):
		if self._thread is not None:raise RuntimeError('worker already started')
		self._thread=Thread(target=self._run,name='lpr-tcp',daemon=True);self._thread.start()
	def stop(self):
		self._stop.set()
		if self._socket is not None:
			try:self._socket.shutdown(socket.SHUT_RDWR)
			except OSError:pass
		if self._thread is not None:self._thread.join(timeout=1.)
	def _run(self):
		try:
			while not self._stop.is_set():
				try:
					with connect_board(self.host,self.port,self._stop)as A:
						self._socket=A;A.settimeout(2);self.events.put(('connection','已连接开发板 {}:{}'.format(self.host,self.port)))
						while not self._stop.is_set():
							meta,jpeg=recv_frame(A)
							try:frame=decode_tcp_frame(meta,jpeg)
							except(ValueError,OSError)as B:self.decode_errors+=1;self.events.put(('status','丢弃损坏帧：{}'.format(B)));continue
							self.frames.put(frame)
				except(OSError,EOFError,ValueError)as B:
					if not self._stop.is_set():self.events.put(('connection','连接中断，正在重试：{}'.format(B)))
				finally:self._socket=None
				self._stop.wait(2)
		finally:self.events.put(('closed',None))