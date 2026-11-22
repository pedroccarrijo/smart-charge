import base64
from collections import deque
from datetime import datetime, timezone
import json
import threading
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException

from api.db import connect, audit
from api.security import current_user, operator
from services.common import secret, log

router = APIRouter(prefix="/api/messaging", tags=["Mensageria RabbitMQ"])
lock = threading.Lock()
recent = deque(maxlen=40)
cached = dict(
    available=False,
    sampled_at=None,
    queues=[],
    consumers=[],
    rates={},
    error="Aguardando consulta ao RabbitMQ",
)


def sanitized(value, depth=0):
    if depth > 6:
        return "[limite de profundidade]"
    if isinstance(value, dict):
        return {
            str(key): "[oculto]"
            if any(
                part in str(key).lower()
                for part in (
                    "password",
                    "senha",
                    "secret",
                    "token",
                    "authorization",
                    "cookie",
                    "jwt",
                    "api_key",
                )
            )
            else sanitized(item, depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, list):
        return [sanitized(item, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:1500] + ("…" if len(value) > 1500 else "")
    return value


def record(message, routing_key):
    with lock:
        recent.appendleft(
            dict(
                id=message["id"],
                timestamp=message["timestamp"],
                observed_at=datetime.now(timezone.utc).isoformat(),
                type=message["type"],
                device_id=message["device_id"],
                routing_key=routing_key,
                payload=sanitized(message["payload"]),
            )
        )


def management(path, body=None):
    # Paths are fixed in application code; the browser never supplies broker URLs.
    credentials = base64.b64encode(
        ("monitor:" + secret("rabbit_monitor_password")).encode()
    ).decode()
    request = Request(
        "http://rabbitmq:15672/api/" + path,
        headers={
            "Authorization": "Basic " + credentials,
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urlopen(request, timeout=2) as response:
        return json.load(response)


def rate(stats, key):
    return float(stats.get(key + "_details", {}).get("rate", 0))


def poll(stop):
    global cached
    while not stop.is_set():
        try:
            queues = management("queues/smartcharge")
            consumers = management("consumers/smartcharge")
            exchange = management("exchanges/smartcharge/events")
            queue_rows = [
                dict(
                    name=q["name"],
                    messages=q.get("messages", 0),
                    ready=q.get("messages_ready", 0),
                    unacknowledged=q.get("messages_unacknowledged", 0),
                    consumers=q.get("consumers", 0),
                    publish_rate=rate(q.get("message_stats", {}), "publish"),
                    delivery_rate=rate(q.get("message_stats", {}), "deliver_get"),
                )
                for q in queues
            ]
            consumer_rows = [
                dict(
                    queue=c["queue"]["name"],
                    tag=c["consumer_tag"],
                    user=c.get("channel_details", {}).get("user", ""),
                    ack_required=c.get("ack_required", False),
                    prefetch=c.get("prefetch_count", 0),
                )
                for c in consumers
            ]
            stats = exchange.get("message_stats", {})
            with lock:
                cached = dict(
                    available=True,
                    error=None,
                    sampled_at=datetime.now(timezone.utc).isoformat(),
                    queues=sorted(queue_rows, key=lambda q: q["name"]),
                    consumers=consumer_rows,
                    rates=dict(
                        publish_in=rate(stats, "publish_in"),
                        publish_out=rate(stats, "publish_out"),
                    ),
                )
        except Exception as exc:
            log.warning("RabbitMQ monitoring unavailable (%s)", type(exc).__name__)
            with lock:
                cached = {
                    **cached,
                    "available": False,
                    "error": "Monitoramento do RabbitMQ temporariamente indisponível",
                }
        stop.wait(2)


def snapshot():
    with lock:
        return {**cached, "recent": list(recent)}


@router.get("")
def overview(user=Depends(current_user)):
    return snapshot()


@router.post("/dlq/peek")
def peek(user=Depends(operator)):
    try:
        messages = management(
            "queues/smartcharge/deadletters/get",
            dict(count=5, ackmode="ack_requeue_true", encoding="auto", truncate=4096),
        )
    except Exception as exc:
        log.warning("DLQ preview unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Não foi possível inspecionar a DLQ") from None
    result = []
    for item in messages:
        try:
            payload = sanitized(json.loads(item["payload"]))
        except (ValueError, TypeError):
            payload = "[Conteúdo não JSON ou maior que o limite de visualização; original preservado na DLQ]"
        result.append(
            dict(
                routing_key=item.get("routing_key"),
                payload=payload,
                redelivered=item.get("redelivered", False),
                payload_bytes=item.get("payload_bytes", 0),
                remaining=item.get("message_count", 0),
            )
        )
    with connect() as conn:
        audit(
            conn,
            "dlq_inspected",
            user["id"],
            details={"count": len(result), "requeued": True},
        )
    return dict(messages=result, preserved=True)
