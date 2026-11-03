import json;from queue import Queue;from threading import Event,Lock,Thread;import serial;from pc_viewer.src.lpr_viewer.models import decode_frame,decode_result;from shared.lpr_wire import PacketKind,StreamParser
class LatestFrameQueue:
	def __init__(self):self._lock=Lock();self._item=None
	def put(self,item):
		with self._lock:self._item=item
	def take(self):
		with self._lock:item=self._item;self._item=None;return item
class SerialWorker:
	def __init__(self,port,baudrate):self.port=port;self.baudrate=int(baudrate);self.frames=LatestFrameQueue();self.events=Queue();self.parser=StreamParser();self.decode_errors=0;self._stop=Event();self._thread=None
	def start(self):
		if self._thread is not None:raise RuntimeError('worker already started')
		self._thread=Thread(target=self._run,name='lpr-serial',daemon=True);self._thread.start()
	def stop(self):
		self._stop.set()
		if self._thread is not None:self._thread.join(timeout=1.)
	def _run(self):
		try:
			with serial.Serial(self.port,self.baudrate,timeout=.1)as A:
				self.events.put(('connection','已连接 {} @ {}'.format(self.port,self.baudrate)))
				while not self._stop.is_set():
					for packet in self.parser.feed(A.read(4096)):
						try:
							if packet.kind==PacketKind.FRAME:self.frames.put(decode_frame(packet))
							elif packet.kind==PacketKind.RESULT:self.events.put(('result',decode_result(packet)))
							elif packet.kind==PacketKind.STATUS:B=json.loads(packet.payload.decode('utf-8'));self.events.put(('status',B))
						except(ValueError,KeyError,TypeError,UnicodeError,json.JSONDecodeError):self.decode_errors+=1
		except(serial.SerialException,OSError,ValueError)as C:self.events.put(('connection','串口断开：{}'.format(C)))
		finally:self.events.put(('closed',None))