"""Shared event contract and authenticated service connections."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from uuid import UUID, uuid4

import pika

DEVICES = ("ponto01", "ponto02", "ponto03")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logging.getLogger("pika").setLevel(logging.WARNING)
log = logging.getLogger("smartcharge")


def secret(name):
    return (Path("/run/secrets") / name).read_text().strip()


def rabbit(user):
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host="rabbitmq",
            virtual_host="smartcharge",
            credentials=pika.PlainCredentials(user, secret("rabbit_password")),
            heartbeat=60,
            blocked_connection_timeout=30,
            socket_timeout=10,
        )
    )
    channel = connection.channel()
    channel.basic_qos(prefetch_count=20)
    channel.confirm_delivery()
    return connection, channel


def event(kind, device, payload, correlation_id=None):
    result = dict(
        id=str(uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        type=kind,
        device_id=device,
        payload=payload,
    )
    if correlation_id:
        result["correlation_id"] = correlation_id
    return result


def decode(body, kind=None):
    result = json.loads(body)
    UUID(result["id"])
    stamp = datetime.fromisoformat(result["timestamp"])
    allowed = (
        "telemetry",
        "command",
        "prediction",
        "alert",
        "job_generate",
        "job_train",
        "job_progress",
    )
    if stamp.tzinfo is None or result["type"] not in allowed:
        raise ValueError("Invalid timestamp or device")
    if (
        result["type"] in ("telemetry", "command", "prediction", "alert")
        and result["device_id"] not in DEVICES
    ):
        raise ValueError("Invalid device")
    if result["type"].startswith("job_") and result["device_id"] is not None:
        raise ValueError("Job events are not device telemetry")
    if not isinstance(result["payload"], dict):
        raise ValueError("Invalid event")
    if kind and result["type"] != kind:
        raise ValueError("Unexpected event type")
    return result


def publish(channel, key, message):
    channel.basic_publish(
        exchange="events",
        routing_key=key,
        body=json.dumps(message, allow_nan=False).encode(),
        mandatory=True,
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            message_id=message["id"],
            expiration="30000" if message["type"] == "command" else None,
        ),
    )


def mark_healthy():
    Path("/tmp/heartbeat").touch()


def supervise(run):
    while True:
        try:
            run()
        except Exception as exc:
            # Do not print connection URLs or credentials in exception messages.
            log.warning(
                "Connection/processing interrupted (%s); retry in 3s",
                type(exc).__name__,
            )
            time.sleep(3)
