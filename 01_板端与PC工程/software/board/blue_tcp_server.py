import argparse,json,socket,time,cv2;from shared.ethernet_wire import encode_frame;from software.board.blue_pipeline import recognize_frame
def make_message(frame,result,capture_ms,preview_long_side=640):
	height,width=frame.shape[:2];A=min(1.,preview_long_side/max(width,height));B=max(1,round(width*A));C=max(1,round(height*A));D=cv2.resize(frame,(B,C),interpolation=cv2.INTER_AREA);E,F=cv2.imencode('.jpg',D,[cv2.IMWRITE_JPEG_QUALITY,75])
	if not E:raise RuntimeError('JPEG encoding failed')
	meta=dict(result);meta.update({'version':1,'capture_ms':capture_ms,'view_w':B,'view_h':C});return encode_frame(meta,F.tobytes())
def _camera_frames(device,count,backend='uvc'):
	if backend=='ov5640':
		from software.board.ov5640_capture import OV5640Capture as B;from software.board.ov5640_profile import apply_auto_gain_ceiling as C
		with B(device)as A:
			C()
			for D in range(12):A.read()
			frame_id=0
			while count<=0 or frame_id<count:D,frame=A.read();frame_id+=1;yield(frame_id,frame)
		return
	if backend!='uvc':raise ValueError('unknown camera backend: '+backend)
	camera=cv2.VideoCapture(device,cv2.CAP_V4L2)
	if not camera.isOpened():raise RuntimeError('USB camera failed to open: '+device)
	try:
		frame_id=0
		while count<=0 or frame_id<count:
			E,frame=camera.read()
			if not E or frame is None:raise RuntimeError('USB camera stopped producing frames')
			frame_id+=1;yield(frame_id,frame)
	finally:camera.release()
def serve(bind,port,image=None,camera=None,frames=0,prototxt='/root/car_ocr/model/ocr.prototxt',weights='/root/car_ocr/model/ocr.caffemodel',camera_backend='uvc'):
	if(image is None)==(camera is None):raise ValueError('select exactly one static image or USB camera')
	network=cv2.dnn.readNetFromCaffe(prototxt,weights)
	with socket.socket(socket.AF_INET,socket.SOCK_STREAM)as A:
		A.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);A.bind((bind,port));A.listen(1);print('BLUE_TCP_READY {}:{}'.format(bind,port),flush=True)
		with A.accept()[0]as D:
			print('BLUE_TCP_CONNECTED',flush=True)
			if image is not None:
				frame=cv2.imread(image)
				if frame is None:raise ValueError('unable to read image: '+image)
				B=(1,frame),
			else:B=_camera_frames(camera,frames,camera_backend)
			for(frame_id,frame)in B:
				E=int(time.time()*1000)
				try:result=recognize_frame(frame,frame_id,network)
				except(OSError,ValueError,TimeoutError)as F:result={'frame_id':frame_id,'src_w':frame.shape[1],'src_h':frame.shape[0],'state':'PL_ERROR','detections':[],'error':str(F)[:160]}
				C=make_message(frame,result,E);D.sendall(C);print(json.dumps({'frame_id':frame_id,'state':result['state'],'detections':result['detections'],'bytes':len(C)},ensure_ascii=True),flush=True)
def main():parser=argparse.ArgumentParser();parser.add_argument('--bind',default='169.254.72.156');parser.add_argument('--port',type=int,default=8767);A=parser.add_mutually_exclusive_group(required=True);A.add_argument('--image');A.add_argument('--camera');parser.add_argument('--camera-backend',choices=('uvc','ov5640'),default='uvc');parser.add_argument('--frames',type=int,default=0,help='camera frame count; 0 means continuous');args=parser.parse_args();serve(args.bind,args.port,image=args.image,camera=args.camera,frames=args.frames,camera_backend=args.camera_backend)
if __name__=='__main__':main()