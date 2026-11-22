from datetime import datetime, timezone
from pathlib import Path
import os
import time
from uuid import UUID, uuid5, NAMESPACE_URL

import joblib

from api.db import connect
from services.common import (
    DEVICES,
    decode,
    event,
    log,
    mark_healthy,
    publish,
    rabbit,
    supervise,
)
from services.ml.features import VERSION, FEATURES
from services.ml.live import LiveEquipment


def run():
    connection, channel = rabbit("inference")
    channel.basic_qos(prefetch_count=200)
    with connect() as conn:
        active_alerts = conn.execute(
            "SELECT device_id,severity FROM predictive_alerts WHERE active"
        ).fetchall()
    levels = {row["device_id"]: row["severity"] for row in active_alerts}
    equipment = {
        device: LiveEquipment(levels.get(device, "normal")) for device in DEVICES
    }
    bundle, model_id, requested_id, model_warning = None, None, None, None
    checked, skipped = 0.0, 0
    max_age = max(30, 3 * float(os.getenv("SIMULATION_INTERVAL", "1")))

    def reload_model():
        nonlocal bundle, model_id, requested_id, model_warning, checked
        if time.monotonic() - checked < 3:
            return
        checked = time.monotonic()
        with connect() as conn:
            model = conn.execute(
                "SELECT id FROM model_versions WHERE active AND accepted"
            ).fetchone()
        requested_id = str(model["id"]) if model else None
        if requested_id == model_id:
            return
        if requested_id is None:
            bundle, model_id, model_warning = None, None, None
            return
        try:
            # Only trusted, locally generated artifacts; no user-supplied pickle/path.
            path = Path("/artifacts/models") / str(UUID(requested_id)) / "models.joblib"
            candidate = joblib.load(path)
            if (
                candidate["feature_version"] != VERSION
                or candidate["features"] != FEATURES
            ):
                raise ValueError("Incompatible feature contract")
            if set(candidate["models"]) != {"health", "rul_hours"}:
                raise ValueError("Missing regressors")
            bundle, model_id, model_warning = candidate, requested_id, None
            for device in equipment.values():
                device.previous_health = None
                device.hysteresis.bad = device.hysteresis.critical = (
                    device.hysteresis.good
                ) = 0
            log.info("Inference loaded model version %s", model_id)
        except Exception as exc:
            model_warning = "Não foi possível carregar a versão aprovada; mantendo a última versão válida"
            log.warning(
                "Model version %s not loaded (%s)", requested_id, type(exc).__name__
            )

    def consume(ch, method, properties, body):
        nonlocal skipped
        try:
            message = decode(body, "telemetry")
            source_time = datetime.fromisoformat(message["timestamp"])
            age = (datetime.now(timezone.utc) - source_time).total_seconds()
            if age > max_age or age < -5:
                skipped += 1
                ch.basic_ack(method.delivery_tag)
                return
            device = equipment[message["device_id"]]
            if not device.add(message):
                ch.basic_ack(method.delivery_tag)
                return
            if bundle is None:
                result, transition = (
                    dict(
                        status="no_model",
                        health=None,
                        rul_hours=None,
                        samples=len(device.rows),
                    ),
                    None,
                )
            else:
                result, transition = device.predict(bundle)
            result.update(
                model_id=model_id,
                requested_model_id=requested_id,
                model_warning=model_warning,
                source_timestamp=message["timestamp"],
                telemetry_id=message["id"],
            )
        except (ValueError, KeyError, TypeError, OverflowError):
            log.warning("Invalid inference telemetry sent to DLQ")
            ch.basic_nack(method.delivery_tag, requeue=False)
            return
        prediction = event("prediction", message["device_id"], result, message["id"])
        prediction["id"] = str(
            uuid5(NAMESPACE_URL, f"prediction:{message['id']}:{model_id}")
        )
        publish(ch, f"predictions.station.power.{message['device_id']}", prediction)
        if transition is not None:
            reason = (
                "Saúde abaixo de 40 ou RUL abaixo de 24 h"
                if transition == "critical"
                else "Saúde abaixo de 70 ou RUL abaixo de 72 h"
                if transition == "warning"
                else "Saúde ≥ 75 e RUL ≥ 84 h por dez previsões consecutivas"
            )
            alert = event(
                "alert",
                message["device_id"],
                dict(
                    level=transition,
                    reason=reason,
                    model_id=model_id,
                    source_timestamp=message["timestamp"],
                    health=result["health"],
                    rul_hours=result["rul_hours"],
                ),
                message["id"],
            )
            alert["id"] = str(
                uuid5(NAMESPACE_URL, f"alert:{message['id']}:{model_id}:{transition}")
            )
            publish(ch, f"alerts.station.power.{message['device_id']}", alert)
        ch.basic_ack(method.delivery_tag)

    try:
        reload_model()
        channel.basic_consume("inference.telemetry", consume, auto_ack=False)
        while True:
            reload_model()
            connection.process_data_events(time_limit=0.3)
            mark_healthy()
            if skipped >= 5000:
                log.info(
                    "Ignored %s old readings for live inference; history remains in InfluxDB",
                    skipped,
                )
                skipped = 0
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    supervise(run)
