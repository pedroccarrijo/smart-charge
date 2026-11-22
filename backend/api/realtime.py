"""RabbitMQ consumer, domain session persistence and live snapshots."""

from datetime import datetime, timedelta, timezone
import json
import os
import threading

from api.db import connect, audit
from services.common import DEVICES, decode, log, rabbit, publish

latest = {}
history = []
lock = threading.Lock()
stop = threading.Event()
ready = threading.Event()


def persist_session(conn, message):
    p = message["payload"]
    stamp = datetime.fromisoformat(message["timestamp"])
    if p.get("session_id"):
        started = datetime.fromisoformat(p["session_started_at"])
        completion = (
            stamp + timedelta(minutes=p["estimated_minutes"])
            if p.get("estimated_minutes") is not None
            else None
        )
        status = (
            "ended"
            if not p["occupied"]
            else "completed"
            if p["battery_percent"] >= 100
            else "charging"
            if p["power_kw"] > 0
            else "paused"
        )
        conn.execute(
            """UPDATE charging_sessions SET status='ended',ended_at=%s
            WHERE device_id=%s AND id<>%s AND ended_at IS NULL AND last_seen_at<=%s""",
            (started, message["device_id"], p["session_id"], started),
        )
        conn.execute(
            """INSERT INTO charging_sessions(id,device_id,started_at,last_seen_at,ended_at,status,
            initial_battery_percent,battery_percent,capacity_kwh,power_kw,energy_kwh,estimated_minutes,estimated_completion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at,
            ended_at=coalesce(charging_sessions.ended_at,excluded.ended_at),
            status=excluded.status,battery_percent=excluded.battery_percent,power_kw=excluded.power_kw,
            energy_kwh=excluded.energy_kwh,estimated_minutes=excluded.estimated_minutes,
            estimated_completion=excluded.estimated_completion
            WHERE excluded.last_seen_at>=charging_sessions.last_seen_at
            AND (charging_sessions.ended_at IS NULL OR excluded.status='ended')""",
            (
                p["session_id"],
                message["device_id"],
                started,
                stamp,
                stamp if not p["occupied"] else None,
                status,
                p["initial_battery_percent"],
                p["battery_percent"],
                p["capacity_kwh"],
                p["power_kw"],
                p["energy_kwh"],
                p.get("estimated_minutes"),
                completion,
            ),
        )
    if p.get("last_command_id"):
        command = conn.execute(
            """UPDATE command_outbox SET applied_at=%s
            WHERE id=%s AND device_id=%s AND applied_at IS NULL RETURNING user_id""",
            (stamp, p["last_command_id"], message["device_id"]),
        ).fetchone()
        if command:
            audit(
                conn,
                "command_applied",
                command["user_id"],
                message["device_id"],
                {"command_id": p["last_command_id"]},
            )


def consume():
    while not stop.is_set():
        connection = None
        try:
            connection, channel = rabbit("api")

            def receive(ch, method, properties, body):
                try:
                    message = decode(body)
                    from api.messaging import record

                    record(message, method.routing_key)
                    if message["type"] == "job_progress":
                        ch.basic_ack(method.delivery_tag)
                        return
                    if message["type"] == "prediction":
                        from api.insights import receive_prediction

                        receive_prediction(message)
                        ch.basic_ack(method.delivery_tag)
                        return
                    if message["type"] == "alert":
                        from api.insights import persist_alert

                        persist_alert(message)
                        ch.basic_ack(method.delivery_tag)
                        return
                    if message["type"] != "telemetry":
                        raise ValueError("Unexpected realtime event")
                    with connect() as conn:
                        persist_session(conn, message)
                    with lock:
                        device = message["device_id"]
                        previous = latest.get(device)
                        if (
                            previous is None
                            or message["timestamp"] > previous["timestamp"]
                        ):
                            if (
                                previous is None
                                or previous["payload"]["occupied"]
                                != message["payload"]["occupied"]
                            ):
                                history.insert(
                                    0,
                                    dict(
                                        ponto=device[-2:],
                                        status="EM USO"
                                        if message["payload"]["occupied"]
                                        else "DISPONIVEL",
                                        horario=message["timestamp"],
                                    ),
                                )
                                del history[10:]
                            latest[device] = message
                except (ValueError, KeyError, TypeError):
                    log.warning("Invalid realtime message sent to DLQ")
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    return
                ch.basic_ack(method.delivery_tag)

            channel.basic_consume("api.events", receive, auto_ack=False)
            ready.set()
            while not stop.is_set():
                connection.process_data_events(time_limit=0.5)
        except Exception as exc:
            ready.clear()
            log.warning("Realtime consumer reconnecting (%s)", type(exc).__name__)
            stop.wait(3)
        finally:
            ready.clear()
            if connection and connection.is_open:
                connection.close()


def dispatch_commands():
    while not stop.is_set():
        connection = None
        try:
            connection, channel = rabbit("api")
            while not stop.is_set():
                with connect() as conn:
                    commands = conn.execute("""SELECT * FROM command_outbox
                        WHERE published_at IS NULL AND expires_at>now()
                        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 20""").fetchall()
                    for command in commands:
                        publish(
                            channel,
                            f"commands.station.power.{command['device_id']}",
                            command["event"],
                        )
                        from api.messaging import record

                        record(
                            command["event"],
                            f"commands.station.power.{command['device_id']}",
                        )
                        conn.execute(
                            "UPDATE command_outbox SET published_at=now() WHERE id=%s",
                            (command["id"],),
                        )
                        audit(
                            conn,
                            "command_published",
                            command["user_id"],
                            command["device_id"],
                            {"command_id": str(command["id"])},
                        )
                connection.process_data_events(time_limit=0.1)
                stop.wait(0.2)
        except Exception as exc:
            log.warning("Command publisher reconnecting (%s)", type(exc).__name__)
            stop.wait(3)
        finally:
            if connection and connection.is_open:
                connection.close()


def snapshot():
    now = datetime.now(timezone.utc)
    stale = max(10, float(os.getenv("SIMULATION_INTERVAL", "1")) * 3)
    with lock:
        points = []
        for device in DEVICES:
            message = latest.get(device)
            online = bool(
                ready.is_set()
                and message
                and (now - datetime.fromisoformat(message["timestamp"])).total_seconds()
                < stale
            )
            p = dict(message["payload"]) if online else None
            if p is not None:
                p.setdefault("estimated_minutes", None)
            points.append(
                dict(
                    ponto=device[-2:],
                    device_id=device,
                    online=online,
                    status=("EM USO" if p["occupied"] else "DISPONIVEL")
                    if online
                    else "SEM DADOS",
                    horario=message["timestamp"] if message else None,
                    telemetry=p,
                )
            )
        return dict(
            pontos=points, historico=list(history), consumer_online=ready.is_set()
        )


def dispatch_jobs():
    while not stop.is_set():
        connection = None
        try:
            connection, channel = rabbit("api")
            while not stop.is_set():
                with connect() as conn:
                    jobs = conn.execute(
                        "SELECT * FROM jobs WHERE status='queued' AND published_at IS NULL FOR UPDATE SKIP LOCKED LIMIT 1"
                    ).fetchall()
                    for job in jobs:
                        from services.common import event

                        message = event(
                            "job_" + job["kind"], None, {"job_id": str(job["id"])}
                        )
                        publish(channel, "jobs." + job["kind"], message)
                        from api.messaging import record

                        record(message, "jobs." + job["kind"])
                        conn.execute(
                            "UPDATE jobs SET published_at=now() WHERE id=%s",
                            (job["id"],),
                        )
                        audit(
                            conn,
                            "job_published",
                            job["user_id"],
                            details={"job_id": str(job["id"]), "kind": job["kind"]},
                        )
                connection.process_data_events(time_limit=0.2)
                stop.wait(0.3)
        except Exception as exc:
            log.warning("Lab publisher reconnecting (%s)", type(exc).__name__)
            stop.wait(3)
        finally:
            if connection and connection.is_open:
                connection.close()


def sessions():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM charging_sessions ORDER BY last_seen_at DESC LIMIT 30"
        ).fetchall()
