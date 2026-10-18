FROM python:3.11-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 numpy==1.26.4
COPY scripts/capture_frames.py scripts/capture_frames.py
COPY integrations/beagle_eyes/frame_bridge.py integrations/beagle_eyes/frame_bridge.py
RUN useradd --uid 10001 --create-home firesight
USER firesight
CMD ["python", "scripts/capture_frames.py"]
