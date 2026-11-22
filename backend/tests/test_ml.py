import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pyarrow.parquet as pq

from services.ml.features import extract, FEATURES
from services.ml.generation import generate
from services.ml.training import split_equipment


class LabQualityTests(unittest.TestCase):
    def test_features_never_look_at_future_rows(self):
        rng = np.random.default_rng(12)
        signals = rng.normal([40, 25, 399], [2, 1, 1], (100, 3))
        signals[10:15, 0] = np.nan
        hours = np.arange(100) / 60
        power = np.full(100, 20.0)
        full = extract(signals, hours, power)
        prefix = extract(signals[:50], hours[:50], power[:50])
        np.testing.assert_allclose(full[:50], prefix, equal_nan=True)
        self.assertEqual(full.shape[1], len(FEATURES))
        self.assertFalse(
            any(
                name in FEATURES
                for name in (
                    "health",
                    "rul_hours",
                    "time_to_failure_hours",
                    "degrading",
                    "equipment_id",
                )
            )
        )

    def test_equipment_splits_are_disjoint_and_reproducible(self):
        split = split_equipment(120, 42)
        self.assertEqual(split, split_equipment(120, 42))
        train, validation, test = map(set, split.values())
        self.assertFalse(train & validation or train & test or validation & test)
        self.assertEqual(train | validation | test, set(range(120)))

    def test_generation_is_reproducible_and_records_sensor_quality(self):
        config = dict(
            rows=1200,
            equipment=4,
            days=5,
            temperature_sensors=2,
            current_sensors=1,
            voltage_sensors=1,
            failure_percent=50,
            failure_modes=["cooling_loss", "capacitor_wear"],
            noise=1,
            missing_percent=5,
            outlier_percent=2,
            seed=19,
        )
        with TemporaryDirectory() as root:
            first, second = Path(root) / "a", Path(root) / "b"
            result = generate(config, first, lambda *args: None)
            generate(config, second, lambda *args: None)
            self.assertEqual(result["rows"], 1200)
            self.assertEqual(result["sensor_readings"], 4800)
            self.assertEqual(result["failed_equipment"], 2)
            self.assertGreater(result["missing_cells"], 0)
            self.assertGreater(result["outlier_cells"], 0)
            for file in first.iterdir():
                self.assertEqual(file.read_bytes(), (second / file.name).read_bytes())
            self.assertEqual(
                sum(
                    pq.read_metadata(path).num_rows for path in first.glob("*.parquet")
                ),
                1200,
            )

    def test_failed_equipment_degrades_progressively(self):
        config = dict(
            rows=1200,
            equipment=2,
            days=10,
            temperature_sensors=1,
            current_sensors=1,
            voltage_sensors=1,
            failure_percent=100,
            failure_modes=["resistance_growth"],
            noise=0.2,
            missing_percent=0,
            outlier_percent=0,
            seed=42,
        )
        with TemporaryDirectory() as root:
            generate(config, root, lambda *args: None)
            for path in Path(root).glob("*.parquet"):
                table = pq.read_table(path)
                health = table["health"].to_numpy()
                rul = table["rul_hours"].to_numpy()
                true_rul = table["time_to_failure_hours"].to_numpy()
                residual = (
                    table["temperature_c"].to_numpy()
                    - 27
                    - 0.7 * table["power_kw"].to_numpy()
                )
                self.assertLess(health[-30:].mean(), health[:30].mean() - 40)
                self.assertGreater(residual[-30:].mean(), residual[:30].mean() + 3)
                self.assertTrue(np.all(np.diff(rul) <= 0))
                np.testing.assert_allclose(rul, np.clip(true_rul, 0, 168), atol=1e-5)
