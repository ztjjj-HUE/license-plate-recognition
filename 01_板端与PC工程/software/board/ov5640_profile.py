import subprocess;GAIN_CEILING=504
def _transfer(arguments):
	try:return subprocess.check_output(['i2ctransfer','-f','-y','2']+arguments,stderr=subprocess.PIPE,timeout=3)
	except(subprocess.SubprocessError,OSError)as A:raise OSError('OV5640 I2C transfer failed')from A
def _read(register):
	raw=_transfer(['w2@0x3c',str(register>>8),str(register&255),'r1'])
	try:
		value=int(raw.strip(),16)
		if not 0<=value<=255:raise ValueError('register out of range')
		return value
	except ValueError as A:raise OSError('invalid OV5640 register response')from A
def _write(register,value):_transfer(['w3@0x3c',str(register>>8),str(register&255),str(value)])
def apply_auto_gain_ceiling(read=None,write=None):
	read,write=read or _read,write or _write
	if(read(12298),read(12299))!=(86,64):raise OSError('unexpected camera chip; refusing OV5640 profile')
	if read(13571)&3 or read(13318)&1:raise OSError('OV5640 profile requires automatic exposure/gain/WB')
	A=read(14872),read(14873);B=A[0]&252|GAIN_CEILING>>8,GAIN_CEILING&255
	if A==B:return
	try:
		for(register,value)in zip((14872,14873),B):write(register,value)
		if(read(14872),read(14873))!=B:raise OSError('OV5640 gain ceiling readback mismatch')
	except BaseException:
		try:
			for(register,value)in zip((14872,14873),A):write(register,value)
			if(read(14872),read(14873))!=A:raise OSError('restore readback mismatch')
		except BaseException as C:raise OSError('OV5640 profile failed and original ceiling could not be restored')from C
		raise