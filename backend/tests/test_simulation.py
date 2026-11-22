import random
import unittest

from services.simulation import ChargingPoint


class ChargingPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.point = ChargingPoint(1)
        self.rng = random.Random(42)

    def command(self, action, value):
        self.point.command(
            {"id": "test-command", "payload": {"action": action, "value": value}}
        )

    def test_open_contactor_stops_current_and_battery_growth(self):
        self.point.step(10, self.rng)
        battery, energy = self.point.battery_percent, self.point.energy_kwh
        self.command("set_contactor", False)
        reading = self.point.step(60, self.rng)
        self.assertEqual(reading["power_kw"], 0)
        self.assertEqual(reading["current_a"], 0)
        self.assertEqual(self.point.battery_percent, battery)
        self.assertEqual(self.point.energy_kwh, energy)
        self.assertIsNone(reading["estimated_minutes"])

    def test_limit_changes_power_and_energy_consistently(self):
        self.command("set_power_limit", 50)
        reading = self.point.step(60, self.rng)
        self.assertAlmostEqual(reading["power_kw"], 11)
        self.assertAlmostEqual(self.point.energy_kwh, 11 * 0.95 / 60)
        self.assertAlmostEqual(
            self.point.battery_percent, 35 + self.point.energy_kwh / 60 * 100
        )

    def test_protection_has_separate_activation_and_release_thresholds(self):
        self.point.temperature_c = 66
        self.assertTrue(self.point.step(0, self.rng)["automatic_limit_active"])
        self.point.temperature_c = 60
        self.assertTrue(self.point.step(0, self.rng)["automatic_limit_active"])
        self.point.temperature_c = 54
        self.assertFalse(self.point.step(0, self.rng)["automatic_limit_active"])

    def test_empty_bay_never_charges(self):
        self.command("set_occupied", False)
        self.assertEqual(self.point.step(60, self.rng)["power_kw"], 0)
        self.assertEqual(self.point.energy_kwh, 0)

    def test_rejects_invalid_commands_and_preserves_state(self):
        for action, value in [
            ("set_contactor", 1),
            ("set_power_limit", True),
            ("set_power_limit", -1),
            ("set_power_limit", float("nan")),
            ("set_fault", 101),
            ("unknown", 1),
        ]:
            with (
                self.subTest(action=action, value=value),
                self.assertRaises(ValueError),
            ):
                self.command(action, value)
        self.assertEqual(self.point.power_limit_percent, 100)
        self.assertTrue(self.point.contactor_on)

    def test_full_battery_does_not_receive_more_energy(self):
        self.point.battery_percent = 99.999
        self.point.step(3600, self.rng)
        self.assertEqual(self.point.battery_percent, 100)
        self.assertEqual(self.point.step(60, self.rng)["power_kw"], 0)

    def test_fault_degrades_measured_signals_without_publishing_ground_truth(self):
        healthy = self.point.step(60, random.Random(1))
        degraded = ChargingPoint(1, fault_severity=1).step(60, random.Random(1))
        self.assertGreater(degraded["temperature_c"], healthy["temperature_c"])
        self.assertGreater(degraded["current_a"], healthy["current_a"])
        self.assertLess(degraded["voltage_v"], healthy["voltage_v"])
        for label in ("health", "rul", "fault_severity", "failure_time"):
            self.assertNotIn(label, degraded)
