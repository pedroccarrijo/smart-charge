"""Authenticated REST and RabbitMQ-driven WebSocket API."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import threading
from urllib.parse import urlparse

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    Query,
)
from fastapi.encoders import jsonable_encoder
from influxdb_client import InfluxDBClient
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, StrictBool, StrictFloat
from typing import Literal

from api.db import connect, audit
from api import realtime
from api import lab
from api import insights
from api import catalog, messaging
from api import assistant
from api.security import (
    router,
    current_user,
    operator,
    administrator,
    consume_ticket,
    active_session,
)
from services.common import DEVICES, secret, log, event


@asynccontextmanager
async def lifespan(app):
    realtime.stop.clear()
    await asyncio.to_thread(assistant.recover)
    try:
        initial_history = await asyncio.to_thread(history, None)
        with realtime.lock:
            realtime.history[:] = initial_history
    except HTTPException:
        log.warning("Historical snapshot unavailable during startup")
    threads = [
        threading.Thread(target=target, daemon=True)
        for target in (
            realtime.consume,
            realtime.dispatch_commands,
            realtime.dispatch_jobs,
        )
    ]
    for thread in threads:
        thread.start()
    monitor = threading.Thread(
        target=messaging.poll, args=(realtime.stop,), daemon=True
    )
    monitor.start()
    yield
    realtime.stop.set()
    for thread in threads:
        await asyncio.to_thread(thread.join, 3)
    await asyncio.to_thread(monitor.join, 3)


app = FastAPI(title="Smart Charge", version="2.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(lab.router)
app.include_router(catalog.router)
app.include_router(messaging.router)
app.include_router(assistant.router)


@app.get("/api/health")
def health():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "api"}


def query(flux):
    try:
        with InfluxDBClient(
            url="http://influxdb:8086",
            token=secret("influx_token"),
            org="smartcharge",
            timeout=10000,
        ) as client:
            return client.query_api().query(flux)
    except Exception as exc:
        log.warning("InfluxDB query failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Telemetria temporariamente indisponível") from None


@app.get("/api/status")
def status(user=Depends(current_user)):
    return application_snapshot()["pontos"]


def application_snapshot():
    result = realtime.snapshot()
    result["catalog"] = catalog.snapshot()
    by_id = {device["id"]: device for device in result["catalog"]["devices"]}
    for point in result["pontos"]:
        device = by_id.get(point["device_id"], {})
        point["display_name"] = device.get("name", "Estação " + point["ponto"])
        point["commands_enabled"] = device.get("commands_enabled", True)
    return result


@app.get("/api/historico")
def history(user=Depends(current_user)):
    tables = query("""from(bucket: "telemetry") |> range(start: -24h)
        |> filter(fn: (r) => r._measurement == "charging_telemetry" and r._field == "occupied")
        |> group(columns: ["device_id"])
        |> sort(columns: ["_time"])
        |> map(fn: (r) => ({r with occupied: r._value, _value: if r._value then 1 else 0}))
        |> difference(columns: ["_value"], keepFirst: true)
        |> filter(fn: (r) => not exists r._value or r._value != 0)
        |> tail(n: 10)""")
    changes = []
    for table in tables:
        for row in table.records:
            changes.append(
                dict(
                    ponto=row.values["device_id"][-2:],
                    status="EM USO" if row.values["occupied"] else "DISPONIVEL",
                    horario=row.get_time().isoformat(),
                )
            )
    return sorted(changes, key=lambda row: row["horario"], reverse=True)[:10]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["set_contactor", "set_occupied", "set_power_limit", "set_fault"]
    value: StrictBool | StrictFloat

    @field_validator("value", mode="before")
    @classmethod
    def strict_value(cls, value):
        if type(value) not in (bool, int, float):
            raise ValueError("Use booleano ou número")
        return value


@app.post("/api/devices/{device_id}/commands", status_code=202)
def command(device_id: str, data: Command, user=Depends(operator)):
    if device_id not in DEVICES:
        raise HTTPException(404, "Dispositivo não encontrado")
    from services.simulation import ChargingPoint

    message = event("command", device_id, data.model_dump())
    try:
        ChargingPoint(0).command(message)
    except (ValueError, TypeError):
        raise HTTPException(422, "Valor incompatível com o comando") from None
    with connect() as conn:
        # One in-flight command per device makes telemetry confirmation unambiguous.
        target = conn.execute(
            "SELECT * FROM devices WHERE id=%s FOR UPDATE", (device_id,)
        ).fetchone()
        if not target or not target["commands_enabled"]:
            raise HTTPException(
                423, "Novos comandos estão bloqueados no cadastro deste ponto"
            )
        pending = conn.execute(
            """SELECT 1 FROM command_outbox WHERE device_id=%s
            AND applied_at IS NULL AND expires_at>now()""",
            (device_id,),
        ).fetchone()
        if pending:
            raise HTTPException(409, "Aguarde a confirmação do comando anterior")
        conn.execute(
            """INSERT INTO command_outbox(id,user_id,device_id,event,expires_at)
            VALUES (%s,%s,%s,%s,now()+interval '30 seconds')""",
            (message["id"], user["id"], device_id, Jsonb(message)),
        )
        audit(
            conn,
            "command_requested",
            user["id"],
            device_id,
            dict(command_id=message["id"], action=data.action, value=data.value),
        )
    return {"id": message["id"], "status": "pending"}


@app.get("/api/commands")
def commands(user=Depends(current_user)):
    with connect() as conn:
        return conn.execute("""SELECT id,device_id,event->'payload' AS command,created_at,
            CASE WHEN applied_at IS NOT NULL THEN 'applied' WHEN expires_at<now() THEN 'expired'
            WHEN published_at IS NOT NULL THEN 'published' ELSE 'pending' END AS status
            FROM command_outbox ORDER BY created_at DESC LIMIT 20""").fetchall()


@app.get("/api/sessions")
def sessions(user=Depends(current_user)):
    return realtime.sessions()


@app.get("/api/rules")
def rules(user=Depends(current_user)):
    with connect() as conn:
        return conn.execute("SELECT * FROM automation_rules ORDER BY id").fetchall()


@app.get("/api/telemetry/history")
def telemetry_history(
    device_id: Literal["ponto01", "ponto02", "ponto03"],
    minutes: int = Query(default=30, ge=5, le=1440),
    user=Depends(current_user),
):
    # Device is an allowlisted literal; minutes is bounded. No user Flux is accepted.
    window = max(5, minutes * 60 // 180)
    tables = query(f'''from(bucket: "telemetry") |> range(start: -{minutes}m)
        |> filter(fn: (r) => r._measurement == "charging_telemetry" and r.device_id == "{device_id}")
        |> filter(fn: (r) => r._field == "temperature_c" or r._field == "current_a" or r._field == "voltage_v")
        |> aggregateWindow(every: {window}s, fn: mean, createEmpty: false)
        |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> sort(columns: ["_time"]) |> limit(n: 181)''')
    rows = [
        dict(
            timestamp=row.get_time().isoformat(),
            **{
                field: row.values.get(field)
                for field in ("temperature_c", "current_a", "voltage_v")
            },
        )
        for table in tables
        for row in table.records
    ]
    return dict(
        device_id=device_id,
        minutes=minutes,
        aggregation_seconds=window,
        readings=sorted(rows, key=lambda row: row["timestamp"])[:181],
    )


@app.get("/api/devices")
def devices(user=Depends(current_user)):
    with connect() as conn:
        return conn.execute("SELECT * FROM devices ORDER BY id").fetchall()


@app.get("/api/insights")
def get_insights(user=Depends(current_user)):
    return insights.snapshot(realtime.snapshot()["pontos"])


@app.get("/api/devices/components")
def components(user=Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM device_components ORDER BY device_id,id"
        ).fetchall()


@app.get("/api/audit")
def audit_log(user=Depends(administrator)):
    with connect() as conn:
        return conn.execute("""SELECT a.*,u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id
            ORDER BY a.id DESC LIMIT 100""").fetchall()


@app.websocket("/api/ws")
async def websocket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin and urlparse(origin).netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        user = await asyncio.to_thread(consume_ticket, first.get("ticket"))
        if not user:
            await websocket.close(code=1008)
            return
        while True:
            if not await asyncio.to_thread(active_session, user["login_id"]):
                await websocket.close(code=1008)
                return
            snapshot = await asyncio.to_thread(application_snapshot)
            snapshot["sessions"] = await asyncio.to_thread(realtime.sessions)
            snapshot["commands"] = await asyncio.to_thread(commands, user)
            snapshot["lab"] = await asyncio.to_thread(lab.overview)
            snapshot["insights"] = await asyncio.to_thread(
                insights.snapshot, snapshot["pontos"]
            )
            snapshot["messaging"] = messaging.snapshot()
            await websocket.send_json(jsonable_encoder(snapshot))
            await asyncio.sleep(1)
    except (
        WebSocketDisconnect,
        asyncio.TimeoutError,
        ValueError,
        TypeError,
        AttributeError,
    ):
        pass
