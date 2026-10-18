"""Operator-driven map annotations: holds the prompt, runs Gemini on the newest frame, serves the results."""
import asyncio
import base64
import time

from firesight.analysis.annotator import KINDS, annotate_model, build_annotations, detect_with_gemini
from firesight.analysis.gemini import GeminiConfigurationError, GeminiRequestError

MAX_PROMPT_CHARS = 400
MAX_FRAME_AGE_S = 30


class AnnotationService:
    def __init__(self, get_snapshot, detect=detect_with_gemini, fetch_fresh=None):
        # get_snapshot: newest frame the watcher has seen. It goes stale while the watcher is busy analyzing,
        # so fetch_fresh (optional) pulls the newest frame straight from the source instead.
        self.get_snapshot, self.detect, self.fetch_fresh = get_snapshot, detect, fetch_fresh
        self.prompt, self.auto, self.interval_s = "", False, 3.0
        self.annotations, self.error = [], None
        self.busy, self.latency_ms, self.updated, self.last_frame = False, None, None, None
        self.frame_id = None  # frame the current annotations came from
        self.runs = 0

    def configure(self, prompt=None, auto=None, interval_s=None):
        if prompt is not None:
            if not isinstance(prompt, str):
                raise ValueError("prompt must be text")
            prompt = prompt.strip()[:MAX_PROMPT_CHARS]
            if prompt != self.prompt:
                self.annotations, self.last_frame = [], None  # old results answered a different question
            self.prompt = prompt
        if auto is not None:
            self.auto = bool(auto)
        if interval_s is not None:
            self.interval_s = max(1.0, min(60.0, float(interval_s)))
        return self.state()

    def clear(self):
        self.annotations, self.error = [], None
        return self.state()

    def state(self):
        now = time.time()
        live = [a for a in self.annotations if now - a["ts"] <= a["ttl_s"]]
        return {"prompt": self.prompt, "auto": self.auto, "interval_s": self.interval_s, "busy": self.busy,
                "model": annotate_model(), "latency_ms": self.latency_ms, "error": self.error,
                "updated": self.updated, "frame_id": self.frame_id, "runs": self.runs,
                "kinds": KINDS, "annotations": live}

    @staticmethod
    def _age(snap):
        try:
            return time.time() - float(snap["metadata"]["telemetry"]["timestamp"])
        except (KeyError, TypeError, ValueError):
            return float("inf")

    async def _newest_snapshot(self):
        snap = self.get_snapshot()
        if (not snap or self._age(snap) > MAX_FRAME_AGE_S) and self.fetch_fresh:
            try:
                fresh = await asyncio.to_thread(self.fetch_fresh)
            except Exception:
                fresh = None
            if fresh and (not snap or self._age(fresh) < self._age(snap)):
                snap = fresh
        return snap

    async def run_once(self, only_new=False):
        if self.busy:
            return self.state()
        if not self.prompt:
            self.error = "Enter what to annotate first"
            return self.state()
        snap = await self._newest_snapshot()
        if not snap or not snap.get("image"):
            self.error = "No frame yet. Waiting for Beagle Eyes."
            return self.state()
        metadata = snap["metadata"]
        if only_new and snap["frame_id"] == self.last_frame:
            return self.state()
        age = self._age(snap)
        if age > MAX_FRAME_AGE_S:
            self.error = f"Latest Beagle Eyes frame is {age:.0f} s old. Is the video stream still running?"
            return self.state()
        self.busy, self.error = True, None
        started = time.perf_counter()
        try:
            image = base64.b64decode(snap["image"].split(",", 1)[1])
            geo = metadata["telemetry"].get("geo")
            items = await asyncio.to_thread(self.detect, image, self.prompt, geo)
            self.annotations = build_annotations(items, geo, snap["frame_id"], time.time())
            self.last_frame = self.frame_id = snap["frame_id"]
            self.latency_ms = round((time.perf_counter() - started) * 1000)
            self.updated = time.time()
            self.runs += 1
            if not geo or not geo.get("camera"):
                self.error = "Annotations are not placed on the map: start uav_vo.py with --gps-tf"
        except (GeminiConfigurationError, GeminiRequestError, ValueError, KeyError) as error:
            self.error = str(error)
        finally:
            self.busy = False
        return self.state()

    async def run(self):
        """Background loop: when auto is on, annotate each new frame at most every interval_s."""
        while True:
            try:
                if self.auto and self.prompt and not self.busy:
                    started = time.time()
                    await self.run_once(only_new=True)
                    await asyncio.sleep(max(0.0, self.interval_s - (time.time() - started)))
            except Exception as error:  # keep the loop alive
                self.error = f"{type(error).__name__}: {error}"
            await asyncio.sleep(0.25)
