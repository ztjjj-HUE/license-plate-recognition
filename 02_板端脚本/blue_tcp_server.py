"""Serve real board frames, HDMI display, and PL/OCR results over TCP & HDMI."""

import argparse
import datetime
import json
import mmap
import os
import socket
import sys
import time

import cv2
import numpy as np

from shared.ethernet_wire import encode_frame
from software.board.blue_pipeline import PlateTracker, plate_to_ascii, recognize_frame


class HDMIFramebuffer:
    """Linux Framebuffer driver for ALIENTEK Zynq HDMI output."""
    def __init__(self, preferred_device="/dev/fb1"):
        self.device = preferred_device
        self.fd = -1
        self.mmap_buf = None
        self.width = 1280
        self.height = 720
        self.bpp = 32
        self.line_length = 1280 * 4
        self.opened = False
        self._init_fb()

    def _init_fb(self):
        devices = [self.device, "/dev/fb1", "/dev/fb0"]
        for dev in devices:
            if not os.path.exists(dev):
                continue
            try:
                self.fd = os.open(dev, os.O_RDWR | os.O_SYNC)
                fb_name = os.path.basename(dev)
                sysfs = f"/sys/class/graphics/{fb_name}"
                try:
                    with open(f"{sysfs}/virtual_size", "r") as f:
                        w, h = map(int, f.read().strip().split(","))
                        if w > 0 and h > 0:
                            self.width, self.height = w, h
                except Exception:
                    pass
                try:
                    with open(f"{sysfs}/bits_per_pixel", "r") as f:
                        b = int(f.read().strip())
                        if b > 0:
                            self.bpp = b
                except Exception:
                    pass
                try:
                    with open(f"{sysfs}/stride", "r") as f:
                        s = int(f.read().strip())
                        if s > 0:
                            self.line_length = s
                except Exception:
                    self.line_length = self.width * (self.bpp // 8)

                size = self.line_length * self.height
                self.mmap_buf = mmap.mmap(self.fd, size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
                self.opened = True
                self.device = dev
                self.disp_w = self.width
                self.disp_h = self.height // 2 if self.height in (2160, 960, 1440) else self.height
                print(f"[HDMI] Framebuffer opened on {dev}: {self.width}x{self.height} (display {self.disp_w}x{self.disp_h}) @ {self.bpp}bpp", flush=True)
                return
            except Exception as e:
                print(f"[HDMI] Warning: unable to open {dev}: {e}", flush=True)
                if self.fd >= 0:
                    try:
                        os.close(self.fd)
                    except Exception:
                        pass
                    self.fd = -1

    def render(self, frame_bgr, result, tracker, fps=0.0):
        if not self.opened or self.mmap_buf is None:
            return

        dw = self.disp_w
        dh = self.disp_h

        # Create canvas of visible display size
        canvas = np.full((dh, dw, 3), 22, dtype=np.uint8)

        # Layout:
        # Header: height 55
        # Main video (left): width = dw - 480, height = dh - 85
        # Right sidebar: width = 460, height = dh - 85
        side_w = 460
        video_w = dw - side_w - 30
        video_h = dh - 85

        # 1. Header Bar
        cv2.rectangle(canvas, (0, 0), (dw, 55), (45, 30, 20), -1)
        time_str = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        title_str = "ALIENTEK ZYNQ-7010 LPR SYSTEM (HDMI 1080P)"
        cv2.putText(canvas, title_str, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"FPS: {fps:.1f} | {time_str}", (dw - 430, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 230, 255), 2, cv2.LINE_AA)

        # 2. Main Video Box
        fh, fw = frame_bgr.shape[:2]
        scale = min(video_w / fw, video_h / fh)
        vw, vh = int(fw * scale), int(fh * scale)
        vx0 = 15 + (video_w - vw) // 2
        vy0 = 65 + (video_h - vh) // 2

        # Draw box border
        cv2.rectangle(canvas, (vx0 - 2, vy0 - 2), (vx0 + vw + 2, vy0 + vh + 2), (70, 70, 70), 2)

        # Resize video
        disp_frame = cv2.resize(frame_bgr, (vw, vh), interpolation=cv2.INTER_LINEAR)

        # Draw detections on disp_frame
        detections = result.get("detections", [])
        state = result.get("state", "NO_PLATE")
        has_plate = state == "PLATE" and len(detections) > 0

        for det in detections:
            bx1, by1, bx2, by2 = det["bbox_xyxy"]
            sx1, sy1 = int(bx1 * scale), int(by1 * scale)
            sx2, sy2 = int(bx2 * scale), int(by2 * scale)

            color = (50, 255, 100) if det.get("ocr_valid") else (50, 180, 255)
            cv2.rectangle(disp_frame, (sx1, sy1), (sx2, sy2), color, 4)

            plate_text = det.get("display_plate") or det.get("plate", "")
            conf = det.get("confidence_permille", 0) / 10.0
            label = f"{plate_text} ({conf:.1f}%)"

            # Draw badge above box
            tw = max(160, len(label) * 14)
            ty1 = max(0, sy1 - 34)
            cv2.rectangle(disp_frame, (sx1, ty1), (sx1 + tw, ty1 + 32), (160, 50, 20), -1)
            cv2.rectangle(disp_frame, (sx1, ty1), (sx1 + tw, ty1 + 32), color, 2)
            cv2.putText(disp_frame, label, (sx1 + 6, ty1 + 23), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)

        canvas[vy0:vy0 + vh, vx0:vx0 + vw] = disp_frame

        # Status text below video
        st_color = (50, 255, 100) if has_plate else ((100, 180, 255) if state == "OCR_FAILED" else (160, 160, 160))
        st_text = f"STATUS: {state} | LATENCY: {result.get('pl_ms', 0):.1f}ms (PL) + {result.get('ocr_ms', 0):.1f}ms (OCR)"
        cv2.putText(canvas, st_text, (vx0 + 5, vy0 + vh + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, st_color, 1, cv2.LINE_AA)

        # 3. Right Sidebar: Statistics & History
        sx = dw - side_w - 10
        cv2.rectangle(canvas, (sx, 65), (dw - 10, dh - 15), (32, 28, 25), -1)
        cv2.rectangle(canvas, (sx, 65), (dw - 10, dh - 15), (70, 70, 70), 1)

        # Sidebar Title
        cv2.rectangle(canvas, (sx, 65), (dw - 10, 110), (55, 45, 35), -1)
        cv2.putText(canvas, "VEHICLE RECOGNITION", (sx + 25, 98), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

        # Unique Count Card
        unique_cnt = tracker.unique_count if tracker else 0
        cv2.putText(canvas, "TOTAL UNIQUE VEHICLES:", (sx + 20, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (sx + 20, 158), (dw - 25, 220), (25, 40, 60), -1)
        cv2.rectangle(canvas, (sx + 20, 158), (dw - 25, 220), (50, 150, 255), 2)
        cnt_str = f"{unique_cnt} VEHICLES"
        cv2.putText(canvas, cnt_str, (sx + 45, 204), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (50, 230, 255), 3, cv2.LINE_AA)

        # History List
        cv2.putText(canvas, "RECENT RECOGNITIONS:", (sx + 20, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 1, cv2.LINE_AA)
        cv2.line(canvas, (sx + 20, 272), (dw - 25, 272), (90, 90, 90), 1)

        history = tracker.history if tracker else []
        hy = 310
        max_show = min(8, (dh - 300) // 80)
        for i, item in enumerate(history[:max_show]):
            # Item card
            cv2.rectangle(canvas, (sx + 15, hy - 26), (dw - 20, hy + 38), (28, 35, 45), -1)
            cv2.rectangle(canvas, (sx + 15, hy - 26), (dw - 20, hy + 38), (60, 90, 130), 1)

            idx_str = f"#{item.get('index', i+1)}"
            plate_disp = item.get("display_plate") or plate_to_ascii(item.get("plate", ""))
            time_entry = item.get("time", "")
            conf_pct = f"{item.get('confidence_permille', 0)/10:.0f}%"

            cv2.putText(canvas, idx_str, (sx + 22, hy + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 160, 160), 1, cv2.LINE_AA)

            # Draw plate badge
            cv2.rectangle(canvas, (sx + 65, hy - 18), (sx + 230, hy + 24), (140, 45, 15), -1)
            cv2.rectangle(canvas, (sx + 65, hy - 18), (sx + 230, hy + 24), (220, 180, 50), 2)
            cv2.putText(canvas, plate_disp, (sx + 73, hy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)

            cv2.putText(canvas, time_entry, (sx + 245, hy - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 190, 190), 1, cv2.LINE_AA)
            cv2.putText(canvas, conf_pct, (sx + 245, hy + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 240, 120), 2, cv2.LINE_AA)

            hy += 75

        # Write to framebuffer
        try:
            if self.bpp == 32:
                bgra = cv2.cvtColor(canvas, cv2.COLOR_BGR2BGRA)
                raw_bytes = bgra.tobytes()
            elif self.bpp == 16:
                bgr565 = cv2.cvtColor(canvas, cv2.COLOR_BGR2BGR565)
                raw_bytes = bgr565.tobytes()
            else:
                raw_bytes = canvas.tobytes()

            self.mmap_buf.seek(0)
            self.mmap_buf.write(raw_bytes)
        except Exception as e:
            pass


def make_message(frame, result, capture_ms, preview_long_side=640):
    height, width = frame.shape[:2]
    scale = min(1.0, preview_long_side / max(width, height))
    view_width = max(1, round(width * scale))
    view_height = max(1, round(height * scale))
    preview = cv2.resize(frame, (view_width, view_height), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    meta = dict(result)
    meta.update({"version": 1, "capture_ms": capture_ms,
                 "view_w": view_width, "view_h": view_height})
    # Remove custom complex fields before wire protocol validation
    meta.pop("history", None)
    meta.pop("unique_count", None)
    for det in meta.get("detections", []):
        det.pop("display_plate", None)
    return encode_frame(meta, encoded.tobytes())


def _camera_frames(device, count, backend="uvc"):
    if backend == "ov5640":
        from software.board.ov5640_capture import OV5640Capture
        from software.board.ov5640_profile import apply_auto_gain_ceiling
        with OV5640Capture(device) as capture:
            try:
                apply_auto_gain_ceiling()
            except Exception as e:
                print(f"[OV5640] AGC notice: {e}", flush=True)
            for _ in range(12):
                capture.read()
            frame_id = 0
            while count <= 0 or frame_id < count:
                _, frame = capture.read()
                frame_id += 1
                yield frame_id, frame
        return
    if backend != "uvc":
        raise ValueError("unknown camera backend: " + backend)
    camera = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not camera.isOpened():
        raise RuntimeError("USB camera failed to open: " + device)
    try:
        frame_id = 0
        while count <= 0 or frame_id < count:
            ok, frame = camera.read()
            if not ok or frame is None:
                raise RuntimeError("USB camera stopped producing frames")
            frame_id += 1
            yield frame_id, frame
    finally:
        camera.release()


def serve(bind, port, image=None, camera=None, frames=0,
          prototxt="/root/car_ocr/model/ocr.prototxt",
          weights="/root/car_ocr/model/ocr.caffemodel",
          camera_backend="uvc", hdmi_fb="/dev/fb1"):
    if (image is None) == (camera is None):
        raise ValueError("select exactly one static image or camera")

    print("[SERVER] Loading Caffe OCR model...", flush=True)
    network = cv2.dnn.readNetFromCaffe(prototxt, weights)
    print("[SERVER] Caffe model loaded.", flush=True)

    # Initialize HDMI display
    fb = HDMIFramebuffer(hdmi_fb)
    tracker = PlateTracker(cooldown_seconds=12.0, max_history=8)

    # Setup non-blocking TCP listener
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.setblocking(False)
    try:
        listener.bind((bind, port))
        listener.listen(1)
        print(f"[SERVER] BLUE_TCP_READY {bind}:{port}", flush=True)
    except Exception as e:
        print(f"[SERVER] TCP bind warning: {e}", flush=True)

    client_sock = None
    frame_times = []

    if image is not None:
        static_img = cv2.imread(image)
        if static_img is None:
            raise ValueError("unable to read image: " + image)
        source = ((1, static_img),)
    else:
        source = _camera_frames(camera, frames, camera_backend)

    for frame_id, frame in source:
        t_start = time.time()
        captured = int(t_start * 1000)

        # Recognize frame
        try:
            result = recognize_frame(frame, frame_id, network, tracker=tracker)
        except Exception as error:
            result = {"frame_id": frame_id, "src_w": frame.shape[1],
                      "src_h": frame.shape[0], "state": "PL_ERROR",
                      "detections": [], "error": str(error)[:160]}
            result.update(tracker.get_snapshot())

        # Measure FPS
        t_end = time.time()
        frame_times.append(t_end)
        if len(frame_times) > 20:
            frame_times.pop(0)
        fps = len(frame_times) / max(0.001, (frame_times[-1] - frame_times[0])) if len(frame_times) > 1 else 0.0

        # Output to HDMI Monitor
        fb.render(frame, result, tracker, fps=fps)

        # Accept incoming TCP connections non-blockingly
        if client_sock is None:
            try:
                csock, caddr = listener.accept()
                csock.setblocking(False)
                client_sock = csock
                print(f"[SERVER] TCP Client connected from {caddr}", flush=True)
            except (BlockingIOError, socket.error):
                pass

        # Send to TCP client if connected
        if client_sock is not None:
            try:
                wire = make_message(frame, result, captured)
                client_sock.sendall(wire)
            except Exception as e:
                print(f"[SERVER] TCP Client disconnected: {e}", flush=True)
                try:
                    client_sock.close()
                except Exception:
                    pass
                client_sock = None

        if frame_id % 30 == 0:
            det_info = result.get('detections', [])
            plate_info = det_info[0].get('plate', '') if det_info else 'NONE'
            print(f"[FRAME {frame_id}] State: {result.get('state')} | Plate: {plate_info} | Total Unique: {tracker.unique_count} | FPS: {fps:.1f}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="169.254.72.156")
    parser.add_argument("--port", type=int, default=8767)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--image")
    choice.add_argument("--camera")
    parser.add_argument("--camera-backend", choices=("uvc", "ov5640"), default="uvc")
    parser.add_argument("--frames", type=int, default=0,
                        help="camera frame count; 0 means continuous")
    parser.add_argument("--hdmi-fb", default="/dev/fb1")
    args = parser.parse_args()
    serve(args.bind, args.port, image=args.image, camera=args.camera, frames=args.frames,
          camera_backend=args.camera_backend, hdmi_fb=args.hdmi_fb)


if __name__ == "__main__":
    main()
