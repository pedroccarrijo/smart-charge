from datetime import datetime, timedelta, timezone
import unittest

import numpy as np

from services.ml.alerts import AlertState
from services.ml.features import extract
from services.ml.live import LiveEquipment


class Regressor:
    def __init__(self, value):
        self.value, self.last_x = value, None

    def predict(self, x):
        self.last_x = x
        return np.array([self.value])


class InferenceTests(unittest.TestCase):
    def test_three_bad_and_ten_good_predictions_with_margin(self):
        state = AlertState()
        self.assertIsNone(state.update(60, 100))
        self.assertIsNone(state.update(60, 100))
        self.assertEqual(state.update(60, 100), "warning")
        for _ in range(12):
            self.assertIsNone(state.update(72, 80))
        self.assertEqual(state.level, "warning")
        for _ in range(9):
            self.assertIsNone(state.update(80, 100))
        self.assertEqual(state.update(80, 100), "normal")

    def test_critical_and_low_load_do_not_clear_existing_alert(self):
        state = AlertState()
        state.update(20, 10)
        state.update(20, 10)
        self.assertEqual(state.update(20, 10), "critical")
        for _ in range(20):
            state.update(99, 168, loaded=False)
        self.assertEqual(state.level, "critical")
        self.assertEqual(state.good, 0)

    def test_isolated_bad_values_never_trigger(self):
        state = AlertState()
        for _ in range(10):
            state.update(10, 10)
            state.update(90, 140)
        self.assertEqual(state.level, "normal")

    def test_shared_features_ignore_ground_truth_and_duplicate_messages(self):
        device = LiveEquipment()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        models = {"health": Regressor(88), "rul_hours": Regressor(120)}
        for index in range(8):
            message = dict(
                timestamp=(start + timedelta(seconds=index)).isoformat(),
                payload=dict(
                    temperature_c=40 + index / 10,
                    current_a=30,
                    voltage_v=398,
                    power_kw=20,
                    health=0,
                    rul_hours=0,
                    fault_severity=1,
                ),
            )
            self.assertTrue(device.add(message))
        self.assertFalse(device.add(message))
        result, _ = device.predict({"models": models})
        self.assertEqual(result["health"], 88)
        self.assertEqual(result["rul_hours"], 120)
        expected = extract(
            np.array([[40 + i / 10, 30, 398] for i in range(8)]),
            np.array(
                [(start + timedelta(seconds=i)).timestamp() / 3600 for i in range(8)]
            ),
            np.full(8, 20),
        )[-1:]
        np.testing.assert_allclose(expected, models["health"].last_x, equal_nan=True)

    def test_window_warmup_and_gap(self):
        device = LiveEquipment()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        payload = dict(temperature_c=40, current_a=30, voltage_v=398, power_kw=20)
        device.add(dict(timestamp=start.isoformat(), payload=payload))
        result, transition = device.predict({"models": {}})
        self.assertEqual(result["status"], "warming")
        self.assertIsNone(result["health"])
        device.add(
            dict(
                timestamp=(start + timedelta(seconds=200)).isoformat(), payload=payload
            )
        )
        self.assertEqual(len(device.rows), 1)
