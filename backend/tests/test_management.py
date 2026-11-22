import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from api.catalog import ComponentUpdate, check_thresholds
from api.messaging import sanitized


class ManagementValidationTests(unittest.TestCase):
    def test_sensor_threshold_order_and_finite_numbers(self):
        valid = dict(
            name="Temperatura",
            revision=1,
            critical_min=-20,
            normal_min=-10,
            normal_max=55,
            critical_max=65,
        )
        check_thresholds("sensor", ComponentUpdate(**valid))
        for changes in ({"normal_min": 70}, {"critical_max": 40}, {"normal_max": None}):
            with self.assertRaises(HTTPException):
                check_thresholds("sensor", ComponentUpdate(**{**valid, **changes}))
        with self.assertRaises(ValidationError):
            ComponentUpdate(**{**valid, "normal_max": float("nan")})
        with self.assertRaises(ValidationError):
            ComponentUpdate(**{**valid, "id": "outro_dispositivo"})

    def test_actuator_does_not_accept_sensor_thresholds(self):
        with self.assertRaises(HTTPException):
            check_thresholds(
                "actuator",
                ComponentUpdate(
                    name="Contator",
                    revision=1,
                    critical_min=0,
                    normal_min=1,
                    normal_max=2,
                    critical_max=3,
                ),
            )

    def test_monitoring_redacts_secrets_without_mutating_original(self):
        source = {
            "device_id": "ponto01",
            "payload": {
                "password": "sensitive",
                "access_token": "sensitive",
                "nested": [{"api_key": "sensitive", "voltage_v": 400}],
            },
        }
        result = sanitized(source)
        self.assertEqual(result["device_id"], "ponto01")
        self.assertEqual(result["payload"]["password"], "[oculto]")
        self.assertEqual(result["payload"]["nested"][0]["api_key"], "[oculto]")
        self.assertEqual(result["payload"]["nested"][0]["voltage_v"], 400)
        self.assertEqual(source["payload"]["password"], "sensitive")
