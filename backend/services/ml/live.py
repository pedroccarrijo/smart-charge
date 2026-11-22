"""Use sensor values only, with the exact same causal feature code as training."""

from collections import deque
from datetime import datetime

import numpy as np

from services.ml.features import extract, SIGNALS, WINDOW
from services.ml.alerts import AlertState


class LiveEquipment:
    def __init__(self, level="normal"):
        self.rows = deque(maxlen=WINDOW)
        self.hysteresis = AlertState(level=level)
        self.previous_health = None

    def add(self, message):
        stamp = datetime.fromisoformat(message["timestamp"])
        if self.rows and stamp <= self.rows[-1][0]:
            return False
        if self.rows and (stamp - self.rows[-1][0]).total_seconds() > 180:
            self.rows.clear()
            self.previous_health = None
            self.hysteresis.bad = self.hysteresis.critical = self.hysteresis.good = 0
        p = message["payload"]
        # Ground-truth health, RUL, fault severity and session metadata are never read.
        sensors = [float(p.get(key, float("nan"))) for key in SIGNALS]
        power = float(p["power_kw"])
        if not np.isfinite(power) or sum(np.isfinite(sensors)) < 2:
            raise ValueError("Insufficient valid measurements")
        self.rows.append((stamp, sensors, power))
        return True

    def predict(self, bundle):
        if len(self.rows) < 4:
            return dict(
                status="warming", health=None, rul_hours=None, samples=len(self.rows)
            ), None
        x = extract(
            np.array([r[1] for r in self.rows]),
            np.array([r[0].timestamp() / 3600 for r in self.rows]),
            np.array([r[2] for r in self.rows]),
        )[-1:]
        health = float(np.clip(bundle["models"]["health"].predict(x)[0], 0, 100))
        rul = float(np.clip(bundle["models"]["rul_hours"].predict(x)[0], 0, 168))
        if not np.isfinite(health) or not np.isfinite(rul):
            raise ValueError("Nonfinite prediction")
        loaded = self.rows[-1][2] >= 1
        transition = self.hysteresis.update(health, rul, loaded)
        delta = health - self.previous_health if self.previous_health is not None else 0
        trend = "falling" if delta < -1 else "rising" if delta > 1 else "stable"
        self.previous_health = health
        return dict(
            status="ready" if loaded else "low_load",
            health=health,
            rul_hours=rul,
            samples=len(self.rows),
            level=self.hysteresis.level,
            trend=trend,
            rul_at_horizon=rul >= 167,
        ), transition
