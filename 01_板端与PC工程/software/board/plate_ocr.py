import argparse,json,os,time,cv2,numpy as np;LABELS='京沪津渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新0123456789ABCDEFGHJKLMNPQRSTUVWX YZ'.replace(' ','')+'港学使警澳挂军北南广沈兰成济海民航空';BLANK=83
def make_blob(crop):
	if crop is None or crop.size==0:raise ValueError('empty plate crop')
	A=cv2.resize(crop,(140,36));A=cv2.transpose(A);return cv2.dnn.blobFromImage(A,1./255.,(40,160))
def decode_ctc(probabilities):
	A=np.asarray(probabilities)
	if A.ndim==4 and A.shape[-1]==1:A=A[:,:,:,0]
	if A.ndim!=3 or A.shape[0]!=1 or A.shape[1]!=84:raise ValueError('unexpected network output shape: %s'%(A.shape,))
	D=np.argmax(A[0],axis=0);result=[];B=[];C=BLANK
	for(E,index)in enumerate(D):
		index=int(index)
		if index!=C and index!=BLANK:result.append(LABELS[index]);B.append(float(A[0,index,E]))
		C=index
	return''.join(result),sum(B)/len(B)if B else .0
def expected_from_name(name):
	A=os.path.splitext(os.path.basename(name))[0]
	if A.startswith('_'):return A.rsplit('_',1)[-1]
	return A.split('_',1)[0]
def peak_rss_kb():
	with open('/proc/self/status',encoding='ascii')as B:
		for A in B:
			if A.startswith('VmHWM:'):return int(A.split()[1])
def run(paths,prototxt,weights,labels=None):
	if len(LABELS)!=BLANK:raise ValueError('model mapping must have 83 non-blank labels')
	D=time.monotonic();network=cv2.dnn.readNetFromCaffe(prototxt,weights);E=(time.monotonic()-D)*1000;A=[]
	for path in paths:
		crop=cv2.imread(path)
		if crop is None:raise ValueError('could not read image: '+path)
		network.setInput(make_blob(crop),'data');F=time.monotonic();B,G=decode_ctc(network.forward());H=(time.monotonic()-F)*1000;C=(labels or{}).get(os.path.basename(path),expected_from_name(path));A.append({'file':os.path.basename(path),'expected':C,'prediction':B,'exact':B==C,'score':round(G,4),'inference_ms':round(H,1)})
	return A,E
def main():
	parser=argparse.ArgumentParser();parser.add_argument('images',nargs='+');parser.add_argument('--prototxt',required=True);parser.add_argument('--weights',required=True);parser.add_argument('--labels',help='JSON object mapping image filenames to expected plates');args=parser.parse_args();labels=None
	if args.labels:
		with open(args.labels,encoding='utf-8')as B:labels=json.load(B)
	A,C=run(args.images,args.prototxt,args.weights,labels);print(json.dumps({'results':A,'exact':sum(int(item['exact'])for item in A),'total':len(A),'model_load_ms':round(C,1),'peak_rss_kb':peak_rss_kb()},ensure_ascii=True))
if __name__=='__main__':main()