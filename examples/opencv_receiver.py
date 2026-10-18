"""pip install opencv-python; python examples/opencv_receiver.py [RTSP_URL]"""
import os
import sys
import time

os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp')
import cv2

url = sys.argv[1] if len(sys.argv) > 1 else 'rtsp://127.0.0.1:8554/firesight'
try:
    while True:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        try:
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                # Run hazard detection here; send JSON separately to the future hazard API.
                cv2.imshow('FireSight — incoming video', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    raise KeyboardInterrupt
        finally:
            cap.release()
        print('Stream unavailable; retrying in 2 seconds…')
        time.sleep(2)
except KeyboardInterrupt:
    cv2.destroyAllWindows()
