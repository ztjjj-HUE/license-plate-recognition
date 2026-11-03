from dataclasses import dataclass;import mmap,os,struct,time;from shared.blue_packed import PACKED_BYTES,pack_bgr;MEMORY_BASE=1073741824;MEMORY_SIZE=131072;CONTROL_BASE=1073872896;CONTROL_SIZE=4096;FRAME_BYTES=PACKED_BYTES;RESULT_OFFSET=77824;RESULT_WORDS=8
@dataclass(frozen=True)
class LocatorResult:valid:bool;bbox:tuple;blue_count:int;color_id:int;flags:int
def decode_locator_result(words):
	if len(words)!=RESULT_WORDS:raise ValueError('PL result must have eight words')
	A,C,D,E,F,count,B,G=words
	if A not in(0,1)or B not in(0,1):raise ValueError('PL returned an invalid status or color')
	if A and not(B==1 and count>=40 and 0<=C<E<=320 and 0<=D<F<=240):raise ValueError('PL returned an invalid blue-plate rectangle')
	return LocatorResult(bool(A),(C,D,E,F),count,B,G)
def _write_u32(mapped,offset,value):struct.pack_into('<I',mapped,offset,value)
def _read_u32(mapped,offset):return struct.unpack('<I',mapped[offset:offset+4])[0]
def run_mapped(memory,control,packed_frame,timeout=5.,now=None,sleep=None,clear_result=True):
	if not isinstance(packed_frame,bytes)or len(packed_frame)!=FRAME_BYTES:raise ValueError('packed_frame must contain 76800 bytes')
	if len(memory)<MEMORY_SIZE or len(control)<CONTROL_SIZE:raise ValueError('mapped AXI window is too small')
	if timeout<=0:raise ValueError('timeout must be positive')
	now=now or time.monotonic;sleep=sleep or time.sleep;memory[:FRAME_BYTES]=packed_frame
	if clear_result:memory[RESULT_OFFSET:RESULT_OFFSET+RESULT_WORDS*4]=bytes(RESULT_WORDS*4)
	_write_u32(control,16,MEMORY_BASE);_write_u32(control,20,0);_write_u32(control,28,MEMORY_BASE+RESULT_OFFSET);_write_u32(control,32,0);_write_u32(control,0,1);A=now()+timeout
	while now()<=A:
		if _read_u32(control,0)&2:words=struct.unpack_from('<8I',memory,RESULT_OFFSET);return decode_locator_result(words)
		sleep(.001)
	raise TimeoutError('blue locator did not assert ap_done')
def locate_packed_on_pl(packed_frame,timeout=5.,device='/dev/mem'):
	if not isinstance(packed_frame,bytes)or len(packed_frame)!=FRAME_BYTES:raise ValueError('packed_frame must contain 76800 bytes')
	fd=os.open(device,os.O_RDWR|os.O_SYNC)
	try:
		with mmap.mmap(fd,MEMORY_SIZE,offset=MEMORY_BASE,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)as memory:
			with mmap.mmap(fd,CONTROL_SIZE,offset=CONTROL_BASE,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ|mmap.PROT_WRITE)as control:return run_mapped(memory,control,packed_frame,timeout=timeout)
	finally:os.close(fd)
def locate_bgr_on_pl(frame,timeout=5.,device='/dev/mem'):return locate_packed_on_pl(pack_bgr(frame),timeout=timeout,device=device)