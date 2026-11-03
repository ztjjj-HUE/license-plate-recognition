import math,time,cv2,numpy as np;from shared.blue_packed import HEIGHT,WIDTH,pack_bgr;from software.board.blue_pl_runtime import locate_packed_on_pl;from software.board.plate_ocr import LABELS,decode_ctc,make_blob;PROVINCES=LABELS[:31];LETTERS='ABCDEFGHJKLMNPQRSTUVWXYZ'
def _scale_bbox(box,frame_width,frame_height):A,B,C,D=box;return max(0,min(frame_width-1,A*frame_width//WIDTH)),max(0,min(frame_height-1,B*frame_height//HEIGHT)),max(1,min(frame_width,math.ceil(C*frame_width/WIDTH))),max(1,min(frame_height,math.ceil(D*frame_height/HEIGHT)))
def _ocr_crop_box(box,frame_width,frame_height):A,B,C,D=box;E=max(2,round((C-A)*.12));F=max(2,round((D-B)*.25));return max(0,A-E),max(0,B-F),min(frame_width,C+E),min(frame_height,D+F)
def _read_ocr(crop,network):network.setInput(make_blob(crop),'data');return decode_ctc(network.forward())
def _looks_like_blue_plate(text):return len(text)==7 and text[0]in PROVINCES and text[1]in LETTERS and all(A in LETTERS+'0123456789'for A in text[2:])
def recognize_frame(frame_bgr,frame_id,network,locator=locate_packed_on_pl,ocr=None):
	if not isinstance(frame_bgr,np.ndarray)or frame_bgr.ndim!=3 or frame_bgr.shape[2]!=3:raise ValueError('frame must be BGR color')
	if frame_bgr.dtype!=np.uint8 or min(frame_bgr.shape[:2])<=0:raise ValueError('frame must be nonempty uint8')
	if not isinstance(frame_id,int)or frame_id<0:raise ValueError('frame_id must be nonnegative')
	frame_height,frame_width=frame_bgr.shape[:2];H=time.monotonic();I=cv2.resize(frame_bgr,(WIDTH,HEIGHT),interpolation=cv2.INTER_LINEAR);J=pack_bgr(I);D=time.monotonic();B=locator(J);E=time.monotonic();result={'frame_id':frame_id,'src_w':frame_width,'src_h':frame_height,'state':'NO_PLATE','detections':[],'blue_count':B.blue_count,'pack_ms':round((D-H)*1000,2),'pl_ms':round((E-D)*1000,2)}
	if not B.valid:result['ocr_ms']=.0;return result
	box=_scale_bbox(B.bbox,frame_width,frame_height);A=_ocr_crop_box(box,frame_width,frame_height);crop=frame_bgr[A[1]:A[3],A[0]:A[2]];ocr=ocr or _read_ocr
	try:C,F=ocr(crop,network)
	except(cv2.error,ValueError)as K:C,F='',.0;result['ocr_error']=str(K)[:160]
	result['ocr_ms']=round((time.monotonic()-E)*1000,2);G=_looks_like_blue_plate(C);result['state']='PLATE'if G else'OCR_FAILED';result['detections']=[{'bbox_xyxy':list(box),'plate':C,'confidence_permille':max(0,min(1000,round(F*1000))),'ocr_valid':G}];return result