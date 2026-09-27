"""Measure total device memory across the isolated vision and reconstruction processes."""

import subprocess
import threading
import time

from .scene_run import write


class GpuMeasurement:
    def __init__(self, run):
        self.run = run
        self.stop = threading.Event()
        self.peak = 0
        self.samples = 0
        self.devices = []
        self.error = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.is_set():
            try:
                text = subprocess.check_output([
                    "nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
                    "--format=csv,noheader,nounits"], text=True, timeout=10)
                rows = [line.split(", ") for line in text.strip().splitlines()]
                self.devices = [{"name": r[0], "driver": r[1], "total_mib": int(r[2])} for r in rows]
                self.peak = max(self.peak, sum(int(r[3]) for r in rows))
                self.samples += 1
            except Exception as exc:
                self.error = type(exc).__name__
            self.stop.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, kind, value, tb):
        self.stop.set()
        self.thread.join(timeout=12)
        write(self.run / "logs/gpu_measurement.json", {
            "devices": self.devices, "sampled_peak_device_memory_mib": self.peak,
            "sample_count": self.samples, "sampling_interval_seconds": 1,
            "seconds": time.monotonic() - self.started, "success": kind is None,
            "measurement_error": self.error,
            "note": "Whole-device sampled usage, including resident processes; short peaks may be missed.",
        })
