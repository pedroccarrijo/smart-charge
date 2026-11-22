import json
from pathlib import Path

import joblib
import numpy as np
import pyarrow.parquet as pq
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline

from services.ml.features import extract, FEATURES, SIGNALS, VERSION


def score(actual, predicted):
    return dict(
        mae=float(mean_absolute_error(actual, predicted)),
        rmse=float(np.sqrt(mean_squared_error(actual, predicted))),
        r2=float(r2_score(actual, predicted)),
    )


def split_equipment(count, seed):
    ids = np.random.default_rng(seed).permutation(count)
    train_end, validation_end = int(count * 0.7), int(count * 0.85)
    return dict(
        train=ids[:train_end].tolist(),
        validation=ids[train_end:validation_end].tolist(),
        test=ids[validation_end:].tolist(),
    )


def train(config, dataset_dir, model_dir, progress):
    manifest = json.loads((Path(dataset_dir) / "manifest.json").read_text())
    groups = split_equipment(manifest["config"]["equipment"], config["seed"])
    assignment = {device: name for name, ids in groups.items() for device in ids}
    rng = np.random.default_rng(config["seed"])
    chunks = {name: [[], []] for name in groups}
    caps = dict(train=config["max_train_rows"], validation=30000, test=30000)
    for device, filename in enumerate(manifest["partitions"]):
        table = pq.read_table(
            Path(dataset_dir) / filename,
            columns=SIGNALS + ["hours", "power_kw", "health", "rul_hours"],
        )
        arrays = {key: table[key].to_numpy() for key in table.column_names}
        features = extract(
            np.column_stack([arrays[key] for key in SIGNALS]),
            arrays["hours"],
            arrays["power_kw"],
        )
        targets = np.column_stack([arrays["health"], arrays["rul_hours"]])
        name = assignment[device]
        count = min(len(features), max(1, caps[name] // len(groups[name])))
        selected = np.sort(rng.choice(len(features), count, replace=False))
        chunks[name][0].append(features[selected])
        chunks[name][1].append(targets[selected])
        progress(
            5 + (device + 1) / len(manifest["partitions"]) * 25,
            "Calculando atributos causais por equipamento",
        )
    data = {
        name: (np.concatenate(value[0]), np.concatenate(value[1]))
        for name, value in chunks.items()
    }
    models, metrics = {}, {}
    for target_index, target in enumerate(["health", "rul_hours"]):
        x_train, y_train = data["train"][0], data["train"][1][:, target_index]
        x_val, y_val = data["validation"][0], data["validation"][1][:, target_index]
        x_test, y_test = data["test"][0], data["test"][1][:, target_index]
        candidates = []
        for rate in [0.06, 0.12]:
            model = make_pipeline(
                SimpleImputer(strategy="median", keep_empty_features=True),
                HistGradientBoostingRegressor(
                    max_iter=90,
                    max_leaf_nodes=15,
                    learning_rate=rate,
                    l2_regularization=2,
                    early_stopping=False,
                    random_state=config["seed"],
                ),
            )
            model.fit(x_train, y_train)
            candidates.append(
                (float(mean_absolute_error(y_val, model.predict(x_val))), model, rate)
            )
            progress(
                35 + target_index * 25 + rate * 50, f"Ajustando regressão de {target}"
            )
        _, best, rate = min(candidates, key=lambda item: item[0])
        predicted = best.predict(x_test)
        baseline = DummyRegressor(strategy="mean").fit(x_train, y_train)
        measured, base = (
            score(y_test, predicted),
            score(y_test, baseline.predict(x_test)),
        )
        indices = np.linspace(0, len(x_test) - 1, min(1500, len(x_test)), dtype=int)
        importance = permutation_importance(
            best,
            x_test[indices],
            y_test[indices],
            n_repeats=2,
            random_state=config["seed"],
            scoring="neg_mean_absolute_error",
            n_jobs=1,
        )
        sample = np.linspace(0, len(y_test) - 1, min(200, len(y_test)), dtype=int)
        metrics[target] = dict(
            test=measured,
            baseline=base,
            validation=score(y_val, best.predict(x_val)),
            beats_baseline=measured["mae"] < base["mae"]
            and measured["rmse"] < base["rmse"],
            predicted_vs_actual=[
                dict(actual=float(y_test[i]), predicted=float(predicted[i]))
                for i in sample
            ],
            feature_importance=sorted(
                [
                    dict(feature=name, importance=float(value))
                    for name, value in zip(FEATURES, importance.importances_mean)
                ],
                key=lambda row: row["importance"],
                reverse=True,
            ),
            selected_learning_rate=rate,
        )
        models[target] = best
    accepted = all(item["beats_baseline"] for item in metrics.values())
    result = dict(
        targets=metrics,
        accepted=accepted,
        feature_version=VERSION,
        features=FEATURES,
        equipment_split=groups,
        sample_counts={name: len(values[0]) for name, values in data.items()},
        dataset_rows=manifest["rows"],
        algorithm="HistGradientBoostingRegressor",
        baseline="DummyRegressor(mean)",
        rul_horizon_hours=manifest["rul_horizon_hours"],
    )
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    joblib.dump(
        dict(models=models, feature_version=VERSION, features=FEATURES),
        Path(model_dir) / "models.joblib",
    )
    (Path(model_dir) / "metrics.json").write_text(json.dumps(result, allow_nan=False))
    return result
