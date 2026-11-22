"""Prediction hysteresis, independent from transport and model implementation."""

from dataclasses import dataclass


@dataclass
class AlertState:
    level: str = "normal"
    bad: int = 0
    critical: int = 0
    good: int = 0

    def update(self, health, rul, loaded=True):
        if not loaded:
            self.bad = self.critical = self.good = 0
            return None
        self.bad = self.bad + 1 if health < 70 or rul < 72 else 0
        self.critical = self.critical + 1 if health < 40 or rul < 24 else 0
        self.good = self.good + 1 if health >= 75 and rul >= 84 else 0
        previous = self.level
        if self.critical >= 3:
            self.level = "critical"
        elif self.level == "normal" and self.bad >= 3:
            self.level = "warning"
        elif self.good >= 10:
            self.level = "normal"
        return self.level if previous != self.level else None
