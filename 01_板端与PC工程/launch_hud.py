"""带右侧信息栏的上位机入口（新增文件，不修改原 launch.py）。

    py launch_hud.py --auto-connect
    py launch_hud.py --replay pc_viewer\\replay\\smoke.bin
"""

import sys
import types


def _ensure_pyserial():
    """原 GUI 在 import 时就依赖 pyserial；缺失时给个占位实现，避免启动即崩。"""
    try:
        import serial  # noqa: F401
        return True
    except ImportError:
        pass

    class SerialException(IOError):
        pass

    class Serial:
        def __init__(self, *args, **kwargs):
            raise SerialException("未安装 pyserial，串口模式不可用；请用网口连接")

    module = types.ModuleType("serial")
    module.Serial = Serial
    module.SerialException = SerialException

    tools = types.ModuleType("serial.tools")
    list_ports = types.ModuleType("serial.tools.list_ports")
    list_ports.comports = lambda: []
    tools.list_ports = list_ports
    module.tools = tools

    sys.modules["serial"] = module
    sys.modules["serial.tools"] = tools
    sys.modules["serial.tools.list_ports"] = list_ports
    print("[提示] 未安装 pyserial，已使用占位实现：网口可用，串口不可用。", file=sys.stderr)
    return False


def main():
    import argparse
    from pathlib import Path

    import tkinter as tk

    parser = argparse.ArgumentParser(description="车牌识别上位机（带右侧信息栏）")
    parser.add_argument("--replay", type=Path, help="模拟二进制回放，不写记录")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--host", default="169.254.72.156")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--auto-connect", action="store_true")
    parser.add_argument("--records-dir", default=None)
    args = parser.parse_args()

    from pc_viewer.src.lpr_viewer.app_hud import HudViewer

    root = tk.Tk()

    if args.smoke_test:
        from pc_viewer.tools.make_replay import build_replay
        from shared.lpr_wire import StreamParser

        root.withdraw()
        packets = StreamParser().feed(build_replay())
        app = HudViewer(root, replay=True, records_dir=args.records_dir)
        app.accept_replay_packet(packets[0])
        if len(app.canvas.find_withtag("plate_box")) != 1:
            raise RuntimeError("smoke test: expected one box")
        app.accept_replay_packet(packets[-1])
        if app.canvas.find_withtag("plate_box"):
            raise RuntimeError("smoke test: old box not cleared")
        app.close()
        print("smoke test ok")
        return

    app = HudViewer(root, replay=args.replay is not None, records_dir=args.records_dir)
    app.host_var.set(args.host)
    app.tcp_port_var.set(str(args.port))
    if args.auto_connect and args.replay is None:
        root.after(100, app.toggle_connection)
    if args.replay is not None:
        from shared.lpr_wire import StreamParser

        parser2 = StreamParser()
        packets = parser2.feed(args.replay.read_bytes())
        app.connection_var.set(
            "模拟回放：{} 包，CRC 错误 {}（非实机识别，不写记录）".format(len(packets), parser2.crc_errors))
        for index, packet in enumerate(packets):
            root.after(300 + index * 550, lambda item=packet: app.accept_replay_packet(item))
    root.mainloop()


if __name__ == "__main__":
    _ensure_pyserial()
    main()
