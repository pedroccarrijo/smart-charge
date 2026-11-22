import time
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from api.db import connect, audit
from api.security import current_user, administrator

router = APIRouter(prefix="/api/catalog", tags=["Cadastro de dispositivos"])
lock = threading.Lock()
cached, checked = {}, 0.0


def invalidate():
    global checked
    with lock:
        checked = 0


def snapshot():
    global cached, checked
    with lock:
        if time.monotonic() - checked > 2:
            with connect() as conn:
                cached = dict(
                    devices=conn.execute(
                        "SELECT * FROM devices ORDER BY id"
                    ).fetchall(),
                    components=conn.execute(
                        "SELECT * FROM device_components ORDER BY device_id,id"
                    ).fetchall(),
                )
            checked = time.monotonic()
        return cached


class NamedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("Informe um nome")
        return value.strip()


class DeviceUpdate(NamedRecord):
    location: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=300)
    commands_enabled: bool


class ComponentUpdate(NamedRecord):
    normal_min: FiniteFloat | None
    normal_max: FiniteFloat | None
    critical_min: FiniteFloat | None
    critical_max: FiniteFloat | None


def check_thresholds(kind, data):
    values = [data.critical_min, data.normal_min, data.normal_max, data.critical_max]
    if kind == "sensor":
        if any(value is None for value in values) or not (
            values[0] <= values[1] < values[2] <= values[3]
        ):
            raise HTTPException(
                422,
                "As faixas devem respeitar: crítico mínimo ≤ normal mínimo < normal máximo ≤ crítico máximo",
            )
    elif any(value is not None for value in values):
        raise HTTPException(
            422, "Faixas numéricas são configuradas somente nos sensores"
        )


@router.get("")
def get_catalog(user=Depends(current_user)):
    return snapshot()


@router.put("/devices/{device_id}")
def update_device(device_id: str, data: DeviceUpdate, user=Depends(administrator)):
    with connect() as conn:
        previous = conn.execute(
            "SELECT * FROM devices WHERE id=%s FOR UPDATE", (device_id,)
        ).fetchone()
        if not previous:
            raise HTTPException(404, "Ponto não cadastrado")
        if previous["revision"] != data.revision:
            raise HTTPException(
                409, "O cadastro foi alterado. Recarregue antes de salvar"
            )
        saved = conn.execute(
            """UPDATE devices SET name=%s,location=%s,description=%s,commands_enabled=%s,
            revision=revision+1,updated_at=now() WHERE id=%s RETURNING *""",
            (
                data.name,
                data.location.strip(),
                data.description.strip(),
                data.commands_enabled,
                device_id,
            ),
        ).fetchone()
        fields = ["name", "location", "description", "commands_enabled"]
        audit(
            conn,
            "device_updated",
            user["id"],
            device_id,
            {
                "before": {key: previous[key] for key in fields},
                "after": {key: saved[key] for key in fields},
            },
        )
    invalidate()
    return saved


@router.put("/components/{component_id}")
def update_component(
    component_id: str, data: ComponentUpdate, user=Depends(administrator)
):
    with connect() as conn:
        previous = conn.execute(
            "SELECT * FROM device_components WHERE id=%s FOR UPDATE", (component_id,)
        ).fetchone()
        if not previous:
            raise HTTPException(404, "Componente não cadastrado")
        if previous["revision"] != data.revision:
            raise HTTPException(
                409, "O cadastro foi alterado. Recarregue antes de salvar"
            )
        check_thresholds(previous["kind"], data)
        saved = conn.execute(
            """UPDATE device_components SET name=%s,normal_min=%s,normal_max=%s,
            critical_min=%s,critical_max=%s,revision=revision+1,updated_at=now() WHERE id=%s RETURNING *""",
            (
                data.name,
                data.normal_min,
                data.normal_max,
                data.critical_min,
                data.critical_max,
                component_id,
            ),
        ).fetchone()
        fields = ["name", "normal_min", "normal_max", "critical_min", "critical_max"]
        audit(
            conn,
            "component_updated",
            user["id"],
            previous["device_id"],
            {
                "component_id": component_id,
                "before": {key: previous[key] for key in fields},
                "after": {key: saved[key] for key in fields},
            },
        )
    invalidate()
    return saved
