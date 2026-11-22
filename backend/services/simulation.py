"""Small charging model: commands change measured power and battery evolution."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from uuid import uuid4
from services.rules import THERMAL_PROTECTION


@dataclass
class ChargingPoint:
    number: int
    battery_percent: float = 35.0
    temperature_c: float = 29.0
    contactor_on: bool = True
    power_limit_percent: float = 100.0
    fault_severity: float = 0.0
    energy_kwh: float = 0.0
    occupied: bool = True
    capacity_kwh: float = 60.0
    automatic_limit_percent: float = 100.0
    last_command_id: str | None = None
    session_id: str | None = None
    session_started_at: str | None = None
    initial_battery_percent: float | None = None

    def __post_init__(self):
        if self.occupied and self.session_id is None:
            self.start_session()

    def start_session(self):
        self.session_id = str(uuid4())
        self.session_started_at = datetime.now(timezone.utc).isoformat()
        self.initial_battery_percent = self.battery_percent

    def command(self, message):
        payload = message["payload"]
        action, value = payload["action"], payload["value"]
        if action in ("set_contactor", "set_occupied") and isinstance(value, bool):
            if action == "set_contactor":
                self.contactor_on = value
            else:
                if value and not self.occupied:
                    self.battery_percent = 20 + self.number * 15
                    self.energy_kwh = 0
                    self.start_session()
                self.occupied = value
        elif (
            action in ("set_power_limit", "set_fault")
            and type(value) in (float, int)
            and math.isfinite(value)
        ):
            if not 0 <= value <= 100:
                raise ValueError("Expected percentage 0..100")
            if action == "set_power_limit":
                self.power_limit_percent = float(value)
            else:
                self.fault_severity = float(value) / 100
        else:
            raise ValueError("Unsupported actuator command")
        self.last_command_id = message["id"]

    def step(self, seconds, rng):
        # Hysteresis avoids repeatedly toggling the thermal protection.
        if self.temperature_c >= THERMAL_PROTECTION["activate_at_c"]:
            self.automatic_limit_percent = THERMAL_PROTECTION["limited_power_percent"]
        elif self.temperature_c <= THERMAL_PROTECTION["release_at_c"]:
            self.automatic_limit_percent = 100.0
        limit = min(self.power_limit_percent, self.automatic_limit_percent)
        active = self.occupied and self.contactor_on and self.battery_percent < 100
        taper = min(1.0, max(0.1, (100 - self.battery_percent) / 15))
        power = 22 * limit / 100 * taper if active else 0.0
        efficiency = 0.95 - 0.15 * self.fault_severity
        delivered = min(
            power * efficiency * seconds / 3600,
            self.capacity_kwh * (100 - self.battery_percent) / 100,
        )
        self.energy_kwh += delivered
        self.battery_percent = min(
            100.0, self.battery_percent + 100 * delivered / self.capacity_kwh
        )
        voltage = 400 - power * (0.1 + self.fault_severity * 0.6) + rng.gauss(0, 0.25)
        current = power * 1000 / (math.sqrt(3) * voltage)
        target_temp = 27 + power * (0.7 + self.fault_severity * 2.5)
        self.temperature_c += (target_temp - self.temperature_c) * (
            1 - math.exp(-seconds / 45)
        )
        remaining = self.capacity_kwh * (100 - self.battery_percent) / 100
        # Approximation at current power; recalculated when power or taper changes.
        minutes = (
            remaining / (power * efficiency) * 60
            if power > 0 and remaining > 0
            else None
        )
        return dict(
            occupied=self.occupied,
            temperature_c=round(self.temperature_c + rng.gauss(0, 0.12), 3),
            current_a=round(current, 3),
            voltage_v=round(voltage, 3),
            contactor_on=self.contactor_on,
            power_limit_percent=limit,
            requested_limit_percent=self.power_limit_percent,
            automatic_limit_active=self.automatic_limit_percent < 100,
            power_kw=round(power, 4),
            battery_percent=round(self.battery_percent, 5),
            energy_kwh=round(self.energy_kwh, 6),
            estimated_minutes=minutes,
            last_command_id=self.last_command_id,
            session_id=self.session_id,
            session_started_at=self.session_started_at,
            initial_battery_percent=self.initial_battery_percent,
            capacity_kwh=self.capacity_kwh,
        )
