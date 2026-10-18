FROM python:3.11-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 numpy==1.26.4
COPY scripts/beagle_capture.py scripts/beagle_capture.py
COPY integrations/beagle_eyes/jpeg_stream.py integrations/beagle_eyes/jpeg_stream.py
COPY integrations/beagle_eyes/frame_bridge.py integrations/beagle_eyes/frame_bridge.py
RUN useradd --uid 10001 --create-home firesight
USER firesight
CMD ["python", "scripts/beagle_capture.py"]
