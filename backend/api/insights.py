from collections import deque
from datetime import datetime, timezone
import os
import threading
from uuid import UUID

from api.db import connect, audit
from services.common import DEVICES

lock = threading.Lock()
predictions = {}
history = {device: deque(maxlen=60) for device in DEVICES}


def receive_prediction(message):
    p = message["payload"]
    stamp = datetime.fromisoformat(p["source_timestamp"])
    if stamp.tzinfo is None:
        raise ValueError("Missing timezone")
    with lock:
        device = message["device_id"]
        previous = predictions.get(device)
        if previous and stamp <= datetime.fromisoformat(previous["source_timestamp"]):
            return
        predictions[device] = p
        if p.get("health") is not None:
            history[device].append(
                dict(
                    timestamp=p["source_timestamp"],
                    health=p["health"],
                    rul_hours=p["rul_hours"],
                )
            )


def persist_alert(message):
    p = message["payload"]
    level = p["level"]
    if level not in ("normal", "warning", "critical"):
        raise ValueError("Invalid alert level")
    stamp = datetime.fromisoformat(p["source_timestamp"])
    model_id = str(UUID(p["model_id"]))
    device = message["device_id"]
    with connect() as conn:
        conn.execute("SELECT id FROM devices WHERE id=%s FOR UPDATE", (device,))
        inserted = conn.execute(
            "INSERT INTO processed_alert_events(id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id",
            (message["id"],),
        ).fetchone()
        if not inserted:
            return
        last = conn.execute(
            "SELECT max(updated_at) AS stamp FROM predictive_alerts WHERE device_id=%s",
            (device,),
        ).fetchone()
        if last["stamp"] and stamp <= last["stamp"]:
            return
        active = conn.execute(
            "SELECT * FROM predictive_alerts WHERE device_id=%s AND active", (device,)
        ).fetchone()
        if level == "normal":
            if active:
                conn.execute(
                    "UPDATE predictive_alerts SET active=false,closed_at=%s,updated_at=%s,reason=%s WHERE id=%s",
                    (stamp, stamp, p["reason"], active["id"]),
                )
                audit(
                    conn,
                    "predictive_alert_cleared",
                    device_id=device,
                    details={"alert_id": str(active["id"]), "model_id": model_id},
                )
        elif active:
            conn.execute(
                "UPDATE predictive_alerts SET severity=%s,updated_at=%s,model_id=%s,reason=%s WHERE id=%s",
                (level, stamp, model_id, p["reason"], active["id"]),
            )
            audit(
                conn,
                "predictive_alert_updated",
                device_id=device,
                details={"alert_id": str(active["id"]), "severity": level},
            )
        else:
            conn.execute(
                """INSERT INTO predictive_alerts(id,device_id,severity,opened_at,updated_at,model_id,reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (message["id"], device, level, stamp, stamp, model_id, p["reason"]),
            )
            audit(
                conn,
                "predictive_alert_opened",
                device_id=device,
                details={
                    "alert_id": message["id"],
                    "severity": level,
                    "model_id": model_id,
                },
            )


def snapshot(points):
    with connect() as conn:
        model = conn.execute(
            "SELECT id FROM model_versions WHERE active AND accepted"
        ).fetchone()
        alerts = conn.execute(
            "SELECT * FROM predictive_alerts ORDER BY updated_at DESC LIMIT 50"
        ).fetchall()
    now = datetime.now(timezone.utc)
    stale = max(10, 3 * float(os.getenv("SIMULATION_INTERVAL", "1")))
    devices = []
    with lock:
        for point in points:
            device = point["device_id"]
            prediction = predictions.get(device)
            fresh = bool(
                prediction
                and (
                    now - datetime.fromisoformat(prediction["source_timestamp"])
                ).total_seconds()
                < stale
            )
            current = (
                dict(prediction)
                if point["online"] and fresh
                else dict(
                    status="offline" if not point["online"] else "waiting",
                    health=None,
                    rul_hours=None,
                    model_id=None,
                )
            )
            current.update(
                device_id=device,
                history=list(history[device]) if fresh and point["online"] else [],
            )
            devices.append(current)
    return dict(
        devices=devices,
        alerts=alerts,
        active_model_id=str(model["id"]) if model else None,
    )
