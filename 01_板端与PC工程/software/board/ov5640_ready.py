from software.board.ov5640_capture import OV5640Capture
def verify_camera(device='/dev/video0',factory=OV5640Capture):
	for A in range(1,3):
		try:
			with factory(device)as C:
				for D in range(13):B,D=C.read()
			print('OV5640_READY attempt={} sequence={}'.format(A,B),flush=True);return B
		except TimeoutError as E:
			print('OV5640_TIMEOUT attempt={} error={}'.format(A,E),flush=True)
			if A==2:raise
if __name__=='__main__':import signal;signal.alarm(40);verify_camera();signal.alarm(0)