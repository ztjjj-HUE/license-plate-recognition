import numpy as np;WIDTH=320;HEIGHT=240;TILE=8;COLS=WIDTH//TILE;ROWS=HEIGHT//TILE;PACKED_BYTES=WIDTH*HEIGHT
def pack_bgr(frame):
	if not isinstance(frame,np.ndarray)or frame.shape!=(HEIGHT,WIDTH,3):raise ValueError('frame must be a 240x320x3 BGR array')
	if frame.dtype!=np.uint8:raise ValueError('frame must be uint8')
	A=frame[:,:,0].astype(np.uint16);B=frame[:,:,1].astype(np.uint16);C=frame[:,:,2].astype(np.uint16);D=C*77+B*150+A*29>>8;E=(A>60)&(A>C+35)&(A>B+15);F=D.astype(np.uint8)&254|E.astype(np.uint8);return F.tobytes(order='C')
def _integral(tiles):
	sums=[[0]*(COLS+1)for A in range(ROWS+1)]
	for y in range(ROWS):
		A=0
		for x in range(COLS):A+=tiles[y][x];sums[y+1][x+1]=sums[y][x+1]+A
	return sums
def _rectangle(sums,x,y,width,height):return sums[y+height][x+width]-sums[y][x+width]-sums[y+height][x]+sums[y][x]
def locate_packed(frame):
	if not isinstance(frame,bytes)or len(frame)!=PACKED_BYTES:raise ValueError('packed frame must be 76800 bytes')
	D=[[0]*COLS for A in range(ROWS)];E=[[0]*COLS for A in range(ROWS)]
	for y in range(HEIGHT):
		F=0;G=False
		for x in range(WIDTH):
			H=frame[y*WIDTH+x];I=H&254;C=bool(H&1);J,K=y//TILE,x//TILE
			if C:D[J][K]+=1
			if x and(C or G)and abs(I-F)>=15:E[J][K]+=1
			F=I;G=C
	R=_integral(D);S=_integral(E);A=0;L=0;M=0,0,0,0
	for height in range(2,13):
		for width in range(8,41,2):
			if width<height*3 or width>height*8:continue
			N=width*height*TILE*TILE
			for y in range(ROWS-height+1):
				for x in range(COLS-width+1):
					B=_rectangle(R,x,y,width,height)
					if B<40 or B*5<N:continue
					O=_rectangle(S,x,y,width,height)
					if O*100<8*N:continue
					P=O*4//(width*height);Q=B*P*P
					if Q>L:A=B;L=Q;M=x*TILE,y*TILE,(x+width)*TILE,(y+height)*TILE
	return int(A!=0),*M,A,int(A!=0),0