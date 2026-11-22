"""Vectorized life-cycle generator, bounded row groups and reproducible partitions."""

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

BLOCK = 5000
RUL_HORIZON_HOURS = 168


def generate(config, directory, progress):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(config["seed"])
    equipment, rows = config["equipment"], config["rows"]
    failed = np.zeros(equipment, dtype=bool)
    failed[
        rng.choice(
            equipment, round(equipment * config["failure_percent"] / 100), replace=False
        )
    ] = True
    period = config["days"] * 24
    missing, outliers, cells = 0, 0, 0
    files, preview = [], []
    counts = [
        config["temperature_sensors"],
        config["current_sensors"],
        config["voltage_sensors"],
    ]
    for device in range(equipment):
        n = rows // equipment + (device < rows % equipment)
        lifetime = (
            rng.uniform(period * 0.55, period * 0.98)
            if failed[device]
            else period + rng.uniform(72, 360)
        )
        observed = min(period, lifetime)
        lead = rng.uniform(min(48, period * 0.4), min(240, period * 0.9))
        curve = rng.uniform(0.85, 1.4)
        mode = rng.choice(config["failure_modes"])
        factor = {
            "cooling_loss": (1.1, 0.85),
            "capacitor_wear": (0.85, 1.15),
            "resistance_growth": (1, 1),
        }[mode]
        bias = rng.normal(0, [2, 0.35, 1.1])
        phase = rng.uniform(0, 2 * np.pi)
        filename = f"equipment-{device:04}.parquet"
        path = directory / filename
        writer = None
        try:
            for start in range(0, n, BLOCK):
                end = min(n, start + BLOCK)
                hours = np.arange(start, end, dtype=float) * observed / max(1, n - 1)
                severity = np.clip((hours - lifetime + lead) / lead, 0, 1) ** curve
                daily = np.sin(hours * 2 * np.pi / 24 + phase)
                power = (
                    22
                    * (0.80 + 0.20 * daily)
                    * (np.sin(hours * 2 * np.pi / 7 + phase) > -0.65)
                )
                voltage = 400 - 0.1 * power - severity * (2 + 0.6 * power) * factor[1]
                expected = [
                    27
                    + 3 * daily
                    + power * 0.7
                    + severity * (3 + power * 2.3) * factor[0],
                    power * 1000 / (np.sqrt(3) * voltage),
                    voltage,
                ]
                data = dict(
                    equipment_id=np.full(end - start, device, dtype=np.int32),
                    hours=hours,
                    power_kw=power.astype(np.float32),
                    health=np.clip(
                        100 * (1 - severity) + rng.normal(0, 2, end - start), 0, 100
                    ).astype(np.float32),
                    time_to_failure_hours=np.maximum(lifetime - hours, 0).astype(
                        np.float32
                    ),
                    rul_hours=np.clip(lifetime - hours, 0, RUL_HORIZON_HOURS).astype(
                        np.float32
                    ),
                    degrading=(severity > 0.05),
                    failure_mode=np.full(end - start, mode),
                )
                for signal, count, mean, offset, std in zip(
                    ["temperature_c", "current_a", "voltage_v"],
                    counts,
                    expected,
                    bias,
                    [0.8, 0.25, 0.35],
                ):
                    readings = (
                        mean[:, None]
                        + offset
                        + rng.normal(0, std * config["noise"], (end - start, count))
                    )
                    absent = (
                        rng.random(readings.shape) < config["missing_percent"] / 100
                    )
                    absurd = (~absent) & (
                        rng.random(readings.shape) < config["outlier_percent"] / 100
                    )
                    readings += absurd * rng.normal(0, std * 100, readings.shape)
                    readings[absent] = np.nan
                    missing += int(absent.sum())
                    outliers += int(absurd.sum())
                    cells += readings.size
                    for sensor in range(count):
                        data[f"{signal}_sensor_{sensor + 1}"] = readings[
                            :, sensor
                        ].astype(np.float32)
                    valid = np.isfinite(readings).sum(axis=1)
                    data[signal] = np.divide(
                        np.nansum(readings, axis=1),
                        valid,
                        out=np.full(end - start, np.nan),
                        where=valid > 0,
                    ).astype(np.float32)
                table = pa.table(data)
                if writer is None:
                    writer = pq.ParquetWriter(path, table.schema, compression="snappy")
                writer.write_table(table, row_group_size=BLOCK)
                if device == 0 and not preview:
                    preview = [
                        {
                            key: (
                                None
                                if isinstance(value, float) and not np.isfinite(value)
                                else value
                            )
                            for key, value in row.items()
                        }
                        for row in table.slice(0, 8).to_pylist()
                    ]
        finally:
            if writer:
                writer.close()
        files.append(filename)
        progress((device + 1) / equipment * 95, f"Equipamento {device + 1}/{equipment}")
    manifest = dict(
        config=config,
        rows=rows,
        sensor_readings=cells,
        missing_cells=missing,
        outlier_cells=outliers,
        failed_equipment=int(failed.sum()),
        partitions=files,
        rul_horizon_hours=RUL_HORIZON_HOURS,
        preview=preview,
        format="parquet",
        generator_version="power-module-v2",
    )
    (directory / "manifest.json").write_text(
        json.dumps(manifest, allow_nan=False), encoding="utf-8"
    )
    # Training labels stay in lab artifacts, never in device telemetry/progress events.
    return {
        key: value
        for key, value in manifest.items()
        if key not in ("partitions", "preview")
    }
