from collections import deque;from io import BytesIO;from queue import Empty;import time,tkinter as tk;from tkinter import ttk;from PIL import Image,ImageTk;from serial.tools import list_ports;from pc_viewer.src.lpr_viewer.models import decode_frame,decode_result;from pc_viewer.src.lpr_viewer.serial_worker import SerialWorker;from pc_viewer.src.lpr_viewer.tcp_worker import TcpWorker;from shared.lpr_wire import PacketKind
def map_bbox_xyxy(box,src_wh,canvas_wh):
	B,C=src_wh;D,E=canvas_wh
	if min(B,C,D,E)<=0:raise ValueError('image and canvas dimensions must be positive')
	F,G,H,I=box
	if not(0<=F<H<=B and 0<=G<I<=C):raise ValueError('bbox outside original frame')
	A=min(D/B,E/C);J=(D-B*A)/2;K=(E-C*A)/2;return J+F*A,K+G*A,J+H*A,K+I*A
class ViewerApp:
	def __init__(self,root,replay=False):
		self.root=root;self.root.title('启明星 7010 车牌识别上位机'+(' — 模拟回放'if replay else''));self.root.geometry('920x720');self._replay=replay;self._closed=False;self.worker=None;self._photo=None;self._current_frame=None;self._last_frame_at=None;self._frame_times=deque(maxlen=30);A=ttk.Frame(root,padding=8);A.pack(fill='x');ttk.Label(A,text='连接方式').pack(side='left');self.transport_var=tk.StringVar(value='网口');ttk.Combobox(A,textvariable=self.transport_var,values=('网口','串口'),state='readonly',width=7).pack(side='left',padx=(4,12));ttk.Label(A,text='串口').pack(side='left');self.port_var=tk.StringVar();self.port_box=ttk.Combobox(A,textvariable=self.port_var,width=12);self.port_box.pack(side='left',padx=(4,12));ttk.Label(A,text='波特率').pack(side='left');self.baud_var=tk.StringVar(value='115200');ttk.Combobox(A,textvariable=self.baud_var,values=('115200','460800','576000','921600','2000000'),width=10).pack(side='left',padx=(4,12));self.connect_button=ttk.Button(A,text='连接',command=self.toggle_connection);self.connect_button.pack(side='left');ttk.Button(A,text='刷新串口',command=self.refresh_ports).pack(side='left',padx=(8,0));B=ttk.Frame(root,padding=(8,0,8,8));B.pack(fill='x');ttk.Label(B,text='开发板 IP').pack(side='left');self.host_var=tk.StringVar(value='169.254.72.156');ttk.Entry(B,textvariable=self.host_var,width=20).pack(side='left',padx=(4,12));ttk.Label(B,text='TCP 端口').pack(side='left');self.tcp_port_var=tk.StringVar(value='8767');ttk.Entry(B,textvariable=self.tcp_port_var,width=8).pack(side='left',padx=(4,12));ttk.Label(B,text='网口直连；不会改电脑 Wi-Fi 设置').pack(side='left');self.canvas=tk.Canvas(root,bg='#111820',highlightthickness=0);self.canvas.pack(fill='both',expand=True,padx=8,pady=(0,8));self.canvas.bind('<Configure>',self._on_resize);C=ttk.Frame(root,padding=(8,0,8,8));C.pack(fill='x');self.connection_var=tk.StringVar(value='模拟回放，非实机识别'if replay else'未连接');self.plate_var=tk.StringVar(value='最近稳定车牌：—');self.metrics_var=tk.StringVar(value='预览 0.0 fps · CRC 0 · 解码错误 0');ttk.Label(C,textvariable=self.connection_var).pack(anchor='w');ttk.Label(C,textvariable=self.plate_var,font=('Microsoft YaHei UI',16)).pack(anchor='w',pady=3);ttk.Label(C,textvariable=self.metrics_var).pack(anchor='w');self.refresh_ports()
		if replay:self.connect_button.configure(state='disabled')
		self.root.protocol('WM_DELETE_WINDOW',self.close);self.root.after(50,self._tick)
	def refresh_ports(self):
		A=list(list_ports.comports());self.port_box['values']=[port.device for port in A]
		if not self.port_var.get()and A:B=next((port for port in A if'CH340'in port.description.upper()),A[0]);self.port_var.set(B.device)
	def toggle_connection(self):
		if self.worker is not None:self.worker.stop();self.worker=None;self.connect_button.configure(text='连接');self.connection_var.set('已断开');return
		if self.transport_var.get()=='网口':
			host=self.host_var.get().strip()
			try:
				A=int(self.tcp_port_var.get())
				if not host or not 1<=A<=65535:raise ValueError('invalid TCP endpoint')
			except ValueError:self.connection_var.set('请输入开发板 IP 和有效端口');return
			self.worker=TcpWorker(host,A)
		else:
			port=self.port_var.get().strip()
			try:
				B=int(self.baud_var.get())
				if not port or B<=0:raise ValueError('invalid port or baud')
			except ValueError:self.connection_var.set('请选择串口和有效波特率');return
			self.worker=SerialWorker(port,B)
		self.worker.start();self.connect_button.configure(text='断开');self.connection_var.set('正在连接…')
	def _on_resize(self,_event):
		if self._current_frame is not None:self._draw_frame(self._current_frame)
	def _draw_frame(self,frame):
		A=max(1,self.canvas.winfo_width());B=max(1,self.canvas.winfo_height())
		if frame.codec=='jpeg':
			with Image.open(BytesIO(frame.image_data))as D:
				if D.size!=frame.view_wh:raise ValueError('JPEG dimensions disagree with metadata')
				image=D.convert('RGB')
		else:image=Image.frombytes('L',frame.view_wh,frame.image_data).convert('RGB')
		E=min(A/image.width,B/image.height);H=max(1,round(image.width*E)),max(1,round(image.height*E));image=image.resize(H,Image.Resampling.LANCZOS);self._photo=ImageTk.PhotoImage(image);self.canvas.delete('all');self.canvas.create_image(A/2,B/2,image=self._photo)
		for C in frame.detections:box=map_bbox_xyxy(C.bbox_xyxy,frame.src_wh,(A,B));F=frame.state=='PLATE';G='#35f0aa'if F else'#ffbd59';self.canvas.create_rectangle(*box,outline=G,width=3,tags='plate_box');I='{}  {:.1f}%'.format(C.plate,C.confidence_permille/10)if F else'蓝牌候选 · OCR 未通过';self.canvas.create_text(box[0]+3,max(12,box[1]-16),text=I,fill=G,anchor='nw',font=('Microsoft YaHei UI',15,'bold'))
	def _show_frame(self,frame):
		try:self._draw_frame(frame)
		except(ValueError,OSError):self.connection_var.set('图像解码失败，已丢弃此帧');return
		self._current_frame=frame;self._last_frame_at=time.monotonic();self._frame_times.append(self._last_frame_at)
		if isinstance(self.worker,TcpWorker):
			if frame.state=='PLATE'and frame.detections:item=frame.detections[0];self.plate_var.set('车牌：{}（帧 {}，{:.1f}%）'.format(item.plate,frame.frame_id,item.confidence_permille/10))
			elif frame.state=='OCR_FAILED':self.plate_var.set('帧 {}：检测到蓝牌，字符识别未通过'.format(frame.frame_id))
			elif frame.state=='NO_PLATE':self.plate_var.set('帧 {}：NO_PLATE'.format(frame.frame_id))
			else:self.plate_var.set('帧 {}：PL_ERROR'.format(frame.frame_id))
	def accept_replay_packet(self,packet):
		if packet.kind==PacketKind.FRAME:self._show_frame(decode_frame(packet))
		elif packet.kind==PacketKind.RESULT:self._show_result(decode_result(packet))
	def _show_result(self,result):self.plate_var.set('最近稳定车牌：{}（帧 {}，{:.1f}%）'.format(result.plate,result.frame_id,result.confidence_permille/10))
	def _tick(self):
		if self._closed:return
		if self.worker is not None:
			frame=self.worker.frames.take()
			if frame is not None:self._show_frame(frame)
			while True:
				try:kind,value=self.worker.events.get_nowait()
				except Empty:break
				if kind=='result':self._show_result(value)
				elif kind=='status':self.connection_var.set('设备状态：{}'.format(value))
				elif kind=='connection':self.connection_var.set(value)
				elif kind=='closed':self.connect_button.configure(text='连接');self.worker=None;break
		if self._last_frame_at is not None and time.monotonic()-self._last_frame_at>2:self.canvas.delete('all');self.canvas.create_text(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,text='画面中断',fill='white',font=('Microsoft YaHei UI',22));self._current_frame=None;self._last_frame_at=None
		now=time.monotonic()
		while self._frame_times and now-self._frame_times[0]>5:self._frame_times.popleft()
		A=.0
		if len(self._frame_times)>=2:A=(len(self._frame_times)-1)/max(.001,self._frame_times[-1]-self._frame_times[0])
		B=self.worker.parser.crc_errors if isinstance(self.worker,SerialWorker)else 0;C=self.worker.decode_errors if self.worker else 0;self.metrics_var.set('预览 {:.1f} fps · CRC {} · 解码错误 {}'.format(A,B,C));self.root.after(50,self._tick)
	def close(self):
		self._closed=True
		if self.worker is not None:self.worker.stop()
		self.root.destroy()