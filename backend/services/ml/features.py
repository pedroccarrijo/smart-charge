"""Causal features shared by offline training and future live inference."""

import numpy as np

VERSION = "power-module-v1-window16"
WINDOW = 16
SIGNALS = ["temperature_c", "current_a", "voltage_v"]
FEATURES = [
    f"{sensor}_{stat}"
    for sensor in SIGNALS
    for stat in ("last", "mean", "std", "trend_per_hour", "max")
]
FEATURES += ["power_kw", "hour_sin", "hour_cos", "thermal_residual", "voltage_sag"]


def extract(signals, hours, power):
    values = np.asarray(signals, dtype=np.float64).copy()
    values[~np.isfinite(values)] = np.nan
    for column, (low, high) in enumerate([(-40, 180), (0, 150), (200, 500)]):
        values[:, column] = np.clip(values[:, column], low, high)
    times = np.asarray(hours, dtype=float)
    padded = np.pad(values, ((WINDOW - 1, 0), (0, 0)), constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, WINDOW, axis=0)
    time_windows = np.lib.stride_tricks.sliding_window_view(
        np.pad(times, (WINDOW - 1, 0), constant_values=np.nan), WINDOW
    )
    offsets = time_windows - times[:, None]
    valid = np.isfinite(windows)
    counts = valid.sum(axis=2)
    means = np.divide(
        np.nansum(windows, axis=2),
        counts,
        out=np.full_like(counts, np.nan, dtype=float),
        where=counts > 0,
    )
    variances = np.divide(
        np.nansum((windows - means[:, :, None]) ** 2, axis=2),
        counts,
        out=np.full_like(means, np.nan),
        where=counts > 0,
    )
    dx = offsets[:, None, :]
    tx = np.divide(
        np.nansum(np.where(valid, dx, np.nan), axis=2),
        counts,
        out=np.zeros_like(means),
        where=counts > 0,
    )
    centered = dx - tx[:, :, None]
    numerator = np.nansum(centered * (windows - means[:, :, None]), axis=2)
    denominator = np.nansum(np.where(valid, centered**2, np.nan), axis=2)
    trends = np.divide(
        numerator,
        denominator,
        out=np.full_like(means, np.nan),
        where=(counts > 1) & (denominator > 0),
    )
    maxima = np.max(np.where(valid, windows, -np.inf), axis=2)
    maxima[~np.isfinite(maxima)] = np.nan
    columns = []
    for sensor in range(3):
        columns.extend(
            [
                values[:, sensor],
                means[:, sensor],
                np.sqrt(variances[:, sensor]),
                trends[:, sensor],
                maxima[:, sensor],
            ]
        )
    columns.extend(
        [
            power,
            np.sin(times * 2 * np.pi / 24),
            np.cos(times * 2 * np.pi / 24),
            values[:, 0] - (27 + 0.7 * power),
            400 - values[:, 2],
        ]
    )
    return np.column_stack(columns).astype(np.float32)
