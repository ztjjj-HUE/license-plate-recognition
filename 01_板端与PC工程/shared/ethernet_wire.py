import json,struct;MAX_MESSAGE=2*1024*1024;MAX_JSON=16*1024;HEADER=struct.Struct('>II')
def _validate(meta,jpeg):
	if not isinstance(meta,dict)or meta.get('version')!=1:raise ValueError('unsupported frame metadata')
	for C in('frame_id','capture_ms','src_w','src_h','view_w','view_h'):
		value=meta.get(C)
		if not isinstance(value,int)or isinstance(value,bool)or value<0:raise ValueError('invalid '+C)
	if min(meta['src_w'],meta['src_h'],meta['view_w'],meta['view_h'])<=0:raise ValueError('frame dimensions must be positive')
	if meta.get('state')not in('PLATE','NO_PLATE','OCR_FAILED','PL_ERROR'):raise ValueError('invalid frame state')
	if not isinstance(meta.get('detections'),list):raise ValueError('detections must be a list')
	if not isinstance(jpeg,bytes)or len(jpeg)<4 or not jpeg.startswith(b'\xff\xd8')or not jpeg.endswith(b'\xff\xd9'):raise ValueError('invalid JPEG envelope')
	for A in meta['detections']:
		if not isinstance(A,dict):raise ValueError('invalid detection')
		box=A.get('bbox_xyxy')
		if not isinstance(box,list)or len(box)!=4 or any(not isinstance(A,int)or isinstance(A,bool)for A in box):raise ValueError('invalid detection box')
		D,E,F,G=box
		if not(0<=D<F<=meta['src_w']and 0<=E<G<=meta['src_h']):raise ValueError('detection outside frame')
		if not isinstance(A.get('plate'),str):raise ValueError('invalid plate text')
		B=A.get('confidence_permille')
		if not isinstance(B,int)or isinstance(B,bool)or not 0<=B<=1000:raise ValueError('invalid confidence')
def encode_frame(meta,jpeg):
	_validate(meta,jpeg);A=json.dumps(meta,ensure_ascii=False,separators=(',',':')).encode('utf-8');B=4+len(A)+len(jpeg)
	if not A or len(A)>MAX_JSON or B>MAX_MESSAGE:raise ValueError('frame exceeds protocol bounds')
	return HEADER.pack(B,len(A))+A+jpeg
def _read_exact(sock,count):
	A=bytearray()
	while len(A)<count:
		B=sock.recv(count-len(A))
		if not B:raise EOFError('TCP stream ended mid-frame')
		A.extend(B)
	return bytes(A)
def recv_frame(sock):
	B,A=HEADER.unpack(_read_exact(sock,HEADER.size))
	if not 4<B<=MAX_MESSAGE or not 0<A<=MAX_JSON or A>=B-4:raise ValueError('invalid frame lengths')
	payload=_read_exact(sock,B-4)
	try:meta=json.loads(payload[:A].decode('utf-8'))
	except(UnicodeError,json.JSONDecodeError)as C:raise ValueError('invalid frame JSON')from C
	jpeg=payload[A:];_validate(meta,jpeg);return meta,jpeg