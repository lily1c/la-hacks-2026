"""Beagle Eyes RTMPJpegStream extracted from upstream 7af438b.
Local changes: stable process reference during shutdown; 5s network timeout;
apply sampling before JPEG encoding. No torch/DPVO or GUI dependency.
Original source: vendor/beagle_eyes/scripts/uav_vo.py.
"""
import os
import subprocess
import threading
import time
from pathlib import Path
import cv2
import numpy as np

class RTMPJpegStream:
    """
    Pulls an RTMP stream from MediaMTX (pushed by DJI Mini 5 Pro RC 2) via FFmpeg
    and transcodes it on-the-fly into a continuous pipe of JPEG frames (image2pipe + mjpeg).
    A background daemon thread parses SOI (0xFFD8) and EOI (0xFFD9) markers to always
    keep the newest JPEG frame ready with zero queue lag.
    """

    SOI_MARKER = b"\xff\xd8"
    EOI_MARKER = b"\xff\xd9"

    def __init__(self, rtmp_cfg: dict, static_ip: str):
        self.mode = rtmp_cfg.get("mode", "pull")
        self.pull_host = rtmp_cfg.get("pull_host", "127.0.0.1")
        self.bind_ip = rtmp_cfg.get("bind_ip", "0.0.0.0")
        self.static_ip = static_ip
        self.port = int(rtmp_cfg.get("port", 1935))
        self.app = rtmp_cfg.get("app", "live").strip("/")
        self.stream_key = rtmp_cfg.get("stream_key", "dji").strip("/")
        self.width = int(rtmp_cfg.get("width", 1280))
        self.height = int(rtmp_cfg.get("height", 720))
        self.fps = int(rtmp_cfg.get("fps", 30))
        self.jpeg_quality = int(rtmp_cfg.get("jpeg_quality", 2))
        self.fflags = rtmp_cfg.get("fflags", "nobuffer")
        self.flags = rtmp_cfg.get("flags", "low_delay")
        self.probesize = int(rtmp_cfg.get("probesize", 32768))
        self.analyzeduration = int(rtmp_cfg.get("analyzeduration", 0))
        self.reconnect_delay = float(rtmp_cfg.get("reconnect_delay_sec", 1.0))

        default_path = f"{self.app}/{self.stream_key}" if self.stream_key else self.app
        url_override = rtmp_cfg.get("url_override", "").strip()
        if url_override:
            self.input_url = url_override
            self.public_url = url_override
        else:
            host = self.bind_ip if self.mode == "listen" else self.pull_host
            self.input_url = f"rtmp://{host}:{self.port}/{default_path}"
            self.public_url = f"rtmp://{self.static_ip}:{self.port}/{default_path}"

        self.save_jpegs = bool(rtmp_cfg.get("save_jpegs", False))
        self.jpeg_output_dir = Path(
            os.path.expanduser(rtmp_cfg.get("jpeg_output_dir", "~/beagle_eyes/logs/uav_jpegs"))
        )
        if self.save_jpegs:
            self.jpeg_output_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_jpeg = None
        self._frame_seq = 0
        self._running = False
        self._proc = None
        self._thread = None

    def set_published_path(self, path: str):
        """Updates the local pull URL if DJI RC 2 publishes to a different stream path."""
        path = path.strip("/")
        new_input_url = f"rtmp://{self.pull_host}:{self.port}/{path}"
        if new_input_url != self.input_url:
            print(f"[RTMPJpegStream] Detected DJI stream on path '{path}' -> pulling {new_input_url}")
            self.input_url = new_input_url
            self._terminate_proc()

    def _build_ffmpeg_cmd(self):
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-fflags",
            self.fflags,
            "-flags",
            self.flags,
            "-probesize",
            str(self.probesize),
            "-analyzeduration",
            str(self.analyzeduration),
        ]
        if self.mode == "listen":
            cmd += ["-listen", "1"]

        cmd += [
            "-rw_timeout", "5000000",
            "-i",
            self.input_url,
            "-vf",
            f"fps={self.fps},scale={self.width}:{self.height}",
            "-r",
            str(self.fps),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            str(self.jpeg_quality),
            "-",
        ]
        return cmd

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self):
        while self._running:
            cmd = self._build_ffmpeg_cmd()
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except FileNotFoundError:
                print("Error: 'ffmpeg' binary not found. Install with: sudo apt install ffmpeg")
                self._running = False
                return

            proc = self._proc
            buf = bytearray()
            while self._running and proc.poll() is None:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)

                # Extract all complete JPEG frames in buffer and keep the newest one
                latest_jpg = None
                while True:
                    start = buf.find(self.SOI_MARKER)
                    if start == -1:
                        buf.clear()
                        break
                    end = buf.find(self.EOI_MARKER, start + 2)
                    if end == -1:
                        if start > 0:
                            del buf[:start]
                        break
                    latest_jpg = bytes(buf[start : end + 2])
                    del buf[: end + 2]

                if latest_jpg is not None:
                    arr = np.frombuffer(latest_jpg, dtype=np.uint8)
                    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if bgr is not None:
                        with self._lock:
                            self._latest_jpeg = latest_jpg
                            self._latest_frame = bgr
                            self._frame_seq += 1
                            seq = self._frame_seq

                        if self.save_jpegs:
                            jpg_path = self.jpeg_output_dir / f"frame_{seq:06d}.jpg"
                            jpg_path.write_bytes(latest_jpg)

            self._terminate_proc()
            if self._running:
                time.sleep(self.reconnect_delay)

    def read_latest(self, last_seq: int):
        """Returns (new_seq, bgr_frame, jpeg_bytes) if a newer JPEG frame is available."""
        with self._lock:
            if self._latest_frame is None or self._frame_seq == last_seq:
                return last_seq, None, None
            return self._frame_seq, self._latest_frame.copy(), self._latest_jpeg

    def _terminate_proc(self):
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop(self):
        self._running = False
        self._terminate_proc()
