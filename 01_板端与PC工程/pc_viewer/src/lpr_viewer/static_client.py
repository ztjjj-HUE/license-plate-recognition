import argparse,json,time,serial;from pc_viewer.src.lpr_viewer.upload import prepare_image;from shared.image_upload import encode_upload;from shared.lpr_wire import PacketKind,StreamParser
class UploadFailure(RuntimeError):0
def _wait_marker(port,marker,timeout):
	B=time.monotonic()+timeout;A=bytearray()
	while time.monotonic()<B:
		A.extend(port.read(256))
		if marker in A:return
		if len(A)>4096:del A[:-4096]
	raise UploadFailure('板端接收程序未启动；未收到 {}'.format(marker.decode('ascii')))
def _wait_reply(port,parser,inbox,frame_id,kind,stage,timeout):
	B=time.monotonic()+timeout
	while time.monotonic()<B:
		inbox.extend(parser.feed(port.read(4096)))
		for packet in list(inbox):
			C=kind if isinstance(kind,tuple)else(kind,)
			if packet.frame_id!=frame_id or packet.kind not in C:continue
			inbox.remove(packet)
			try:A=json.loads(packet.payload.decode('utf-8'))
			except(UnicodeError,ValueError)as D:raise UploadFailure('板端返回无效 JSON')from D
			if A.get('frame_id')!=frame_id:raise UploadFailure('板端响应 frame_id 不匹配')
			if stage is not None and A.get('stage')!=stage:
				if A.get('stage')=='error':raise UploadFailure('板端拒收：{}'.format(A.get('code')))
				continue
			if A.get('stage')=='error':raise UploadFailure('板端拒收：{}'.format(A.get('code')))
			if packet.kind==PacketKind.RESULT:A['packet_kind']='RESULT'
			return A
	raise UploadFailure('等待板端 {} 超时；CRC 错误 {}'.format(stage or'STATUS/RESULT',parser.crc_errors))
def upload_prepared(port,prepared,frame_id=1,use_pl=False):
	parser=StreamParser();inbox=[];port.write(b'\r\n')
	if use_pl:port.write(b'cd /home/root/car_lpr_v2 && python3 -u -m software.board.static_receiver --pl\r\n')
	else:port.write(b'cd /home/root/car_lpr_v1 && python3 -u -m software.board.static_receiver\r\n')
	port.flush();_wait_marker(port,b'LPR-READY\r\n',8.);A=encode_upload(frame_id,prepared.pixels,*prepared.sent_wh,seq_start=1);port.write(A[0]);port.flush();B=_wait_reply(port,parser,inbox,frame_id,PacketKind.ACK,'ready',8.)
	if B.get('code')!='OK':raise UploadFailure('板端未准备好：{}'.format(B.get('code')))
	for packet in A[1:]:port.write(packet);port.flush()
	C=_wait_reply(port,parser,inbox,frame_id,PacketKind.ACK,'received',2e1)
	if C.get('code')!='OK':raise UploadFailure('板端图像校验失败：{}'.format(C.get('code')))
	return _wait_reply(port,parser,inbox,frame_id,(PacketKind.STATUS,PacketKind.RESULT),None,8.)
def main(argv=None):
	parser=argparse.ArgumentParser(description='PC 静态图片 → 启明星 7010 串口传输测试');parser.add_argument('image',help='本机图片路径');parser.add_argument('--port',default='COM6');parser.add_argument('--baud',type=int,default=115200);parser.add_argument('--pl',action='store_true',help="use board's verified PL hardware");args=parser.parse_args(argv);prepared=prepare_image(args.image);print('发送 {} → {}×{} GRAY8，{} 字节'.format(prepared.path,*prepared.sent_wh,len(prepared.pixels)))
	with serial.Serial(args.port,args.baud,timeout=.1,write_timeout=15)as port:A=upload_prepared(port,prepared,use_pl=args.pl)
	print('板端状态：{} ({})'.format(A.get('code'),A.get('message','')))
	if A.get('packet_kind')=='RESULT':print('PL 原始结果：{}，框 {}，原始得分 {}（置信度未标定）'.format(A.get('plate'),A.get('bbox_xyxy'),A.get('raw_score')))
	if A.get('code')=='PL_NOT_READY':print('图片传输和 CRC 校验已完成；FPGA 识别核心尚未接入，因此没有车牌结果。')
	return A
if __name__=='__main__':main()