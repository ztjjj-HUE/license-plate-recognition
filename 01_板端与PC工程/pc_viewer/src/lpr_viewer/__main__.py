import argparse;from pathlib import Path;import tkinter as tk;from pc_viewer.src.lpr_viewer.gui import ViewerApp;from shared.lpr_wire import StreamParser
def main():
	parser=argparse.ArgumentParser();parser.add_argument('--replay',type=Path,help='simulated binary stream; never treated as real recognition');parser.add_argument('--smoke-test',action='store_true',help='draw a simulated frame and exit');parser.add_argument('--host',default='169.254.72.156',help='board direct-Ethernet address');parser.add_argument('--port',type=int,default=8767,help='board TCP port');parser.add_argument('--auto-connect',action='store_true',help='connect to board when the window opens');args=parser.parse_args();root=tk.Tk()
	if args.smoke_test:
		root.withdraw();from pc_viewer.tools.make_replay import build_replay as D;B=StreamParser().feed(D());A=ViewerApp(root,replay=True);A.accept_replay_packet(B[0])
		if len(A.canvas.find_withtag('plate_box'))!=1:raise RuntimeError('smoke test did not draw the expected box')
		A.accept_replay_packet(B[-1])
		if A.canvas.find_withtag('plate_box'):raise RuntimeError('smoke test did not clear the old box')
		A.close();return
	A=ViewerApp(root,replay=args.replay is not None);A.host_var.set(args.host);A.tcp_port_var.set(str(args.port))
	if args.auto_connect and args.replay is None:root.after(100,A.toggle_connection)
	if args.replay is not None:
		C=StreamParser();B=C.feed(args.replay.read_bytes());A.connection_var.set('模拟回放：{} 包，CRC 错误 {}（非实机识别）'.format(len(B),C.crc_errors))
		for(index,packet)in enumerate(B):root.after(300+index*550,lambda item=packet:A.accept_replay_packet(item))
	root.mainloop()
if __name__=='__main__':main()