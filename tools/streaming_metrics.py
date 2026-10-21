"""Bounded telemetry with full-run mean/extrema and a reservoir percentile."""
import math
import random

import numpy as np


class StreamingMetric:
    def __init__(self, capacity=1200, seed=17):
        if capacity <= 0:
            raise ValueError("Reservoir capacity must be positive")
        self.capacity = capacity
        self.rng = random.Random(seed)
        self.values = []
        self.count = 0
        self.mean = 0.0
        self.maximum = None

    def add(self, value):
        if value is None or not math.isfinite(value):
            return
        value = float(value)
        self.count += 1
        self.mean += (value - self.mean) / self.count
        self.maximum = value if self.maximum is None else max(value, self.maximum)
        if len(self.values) < self.capacity:
            self.values.append(value)
        else:
            index = self.rng.randrange(self.count)
            if index < self.capacity:
                self.values[index] = value

    def summary(self):
        if not self.count:
            return None
        return {"mean": round(self.mean, 3), "p95": round(float(np.percentile(self.values, 95)), 3),
                "max": self.maximum, "samples": self.count,
                "percentile_samples": len(self.values),
                "p95_is_estimate": self.count > len(self.values),
                "scope": "full_run"}
