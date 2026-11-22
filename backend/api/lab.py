from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ConfigDict

from api.db import connect, audit
from api.security import current_user, administrator

router = APIRouter(prefix="/api/lab", tags=["Laboratório e treinamento"])


class Generation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: int = Field(default=1_000_000, ge=1_000_000, le=3_000_000)
    equipment: int = Field(default=120, ge=20, le=300)
    days: int = Field(default=30, ge=2, le=365)
    temperature_sensors: int = Field(default=1, ge=1, le=4)
    current_sensors: int = Field(default=1, ge=1, le=4)
    voltage_sensors: int = Field(default=1, ge=1, le=4)
    failure_percent: float = Field(default=40, ge=5, le=95)
    failure_modes: list[
        Literal["cooling_loss", "capacitor_wear", "resistance_growth"]
    ] = Field(
        default=["cooling_loss", "capacitor_wear", "resistance_growth"],
        min_length=1,
        max_length=3,
    )
    noise: float = Field(default=1, ge=0.2, le=5)
    missing_percent: float = Field(default=1, ge=0, le=20)
    outlier_percent: float = Field(default=0.2, ge=0, le=5)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


class Training(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    max_train_rows: int = Field(default=200_000, ge=10_000, le=300_000)


def submit(kind, config, user):
    job_id = str(uuid4())
    try:
        with connect() as conn:
            # Persistent resource cap: one generation or training job at a time.
            if conn.execute(
                "SELECT 1 FROM jobs WHERE status IN ('queued','running')"
            ).fetchone():
                raise HTTPException(409, "Aguarde o job atual terminar")
            if kind == "train":
                source = conn.execute(
                    "SELECT 1 FROM jobs WHERE id=%s AND kind='generate' AND status='completed'",
                    (config["dataset_id"],),
                ).fetchone()
                if not source:
                    raise HTTPException(422, "Selecione um conjunto de dados concluído")
            conn.execute(
                "INSERT INTO jobs(id,kind,user_id,config) VALUES (%s,%s,%s,%s)",
                (job_id, kind, user["id"], Jsonb(config)),
            )
            audit(
                conn,
                "job_requested",
                user["id"],
                details={"job_id": job_id, "kind": kind, "config": config},
            )
    except UniqueViolation:
        raise HTTPException(409, "Aguarde o job atual terminar") from None
    return {"id": job_id, "status": "queued"}


@router.post("/generate", status_code=202)
def generate(data: Generation, user=Depends(administrator)):
    return submit("generate", data.model_dump(), user)


@router.post("/train", status_code=202)
def train(data: Training, user=Depends(administrator)):
    return submit("train", data.model_dump(mode="json"), user)


def overview():
    with connect() as conn:
        jobs = conn.execute("""SELECT id,kind,status,progress,message,config,result - 'preview' AS result,created_at,started_at,finished_at
            FROM jobs ORDER BY created_at DESC LIMIT 30""").fetchall()
        models = conn.execute("""SELECT id,job_id,dataset_id,accepted,active,metrics,created_at
            FROM model_versions ORDER BY created_at DESC LIMIT 10""").fetchall()
    return dict(jobs=jobs, models=models)


@router.get("")
def get_lab(user=Depends(current_user)):
    return overview()


@router.post("/models/{model_id}/activate")
def activate(model_id: UUID, user=Depends(administrator)):
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('active_model_version'))")
        model = conn.execute(
            "SELECT accepted FROM model_versions WHERE id=%s", (model_id,)
        ).fetchone()
        if not model:
            raise HTTPException(404, "Versão não encontrada")
        if not model["accepted"]:
            raise HTTPException(
                422, "Somente versões que venceram o baseline podem ser ativadas"
            )
        conn.execute("UPDATE model_versions SET active=false WHERE active")
        conn.execute("UPDATE model_versions SET active=true WHERE id=%s", (model_id,))
        audit(
            conn,
            "model_activated",
            user["id"],
            details={"model_id": str(model_id), "automatic": False},
        )
    return {"id": str(model_id), "active": True}
