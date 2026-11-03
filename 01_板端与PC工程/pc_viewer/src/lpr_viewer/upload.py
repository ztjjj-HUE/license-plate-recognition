from dataclasses import dataclass;from pathlib import Path;from typing import Tuple;from PIL import Image,ImageOps
@dataclass(frozen=True)
class PreparedImage:path:Path;source_wh:Tuple[int,int];sent_wh:Tuple[int,int];content_box:Tuple[int,int,int,int];pixels:bytes
def prepare_image(path,max_wh=(320,240)):
	path=Path(path);width,height=max_wh
	if not 0<width<=640 or not 0<height<=480:raise ValueError('send dimensions must fit within 640×480')
	with Image.open(path)as F:D=ImageOps.exif_transpose(F);G=D.size;H=D.convert('L')
	A=ImageOps.contain(H,max_wh,method=Image.Resampling.LANCZOS);B=(width-A.width)//2;C=(height-A.height)//2;E=Image.new('L',max_wh,color=0);E.paste(A,(B,C));return PreparedImage(path,G,max_wh,(B,C,B+A.width,C+A.height),E.tobytes())
def map_uploaded_bbox(box,prepared):
	A,B,C,D=box;M,N=prepared.sent_wh
	if not(0<=A<C<=M and 0<=B<D<=N):raise ValueError('invalid bbox in sent image')
	E,F,G,H=prepared.content_box;A=max(A,E);B=max(B,F);C=min(C,G);D=min(D,H)
	if A>=C or B>=D:raise ValueError('bbox contains only letterbox padding')
	I,J=prepared.source_wh;K=G-E;L=H-F;return(A-E)*I/K,(B-F)*J/L,(C-E)*I/K,(D-F)*J/L