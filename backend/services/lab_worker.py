"""RabbitMQ job worker: keep AMQP heartbeats responsive during CPU work."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from queue import Queue, Empty
import sys
from uuid import UUID

from psycopg.types.json import Jsonb

from api.db import connect, audit
from services.common import decode, event, log, mark_healthy, publish, rabbit, supervise


def run(kind):
    service = "generator" if kind == "generate" else "trainer"
    queue_name = "generator.jobs" if kind == "generate" else "trainer.jobs"
    connection, channel = rabbit(service)
    channel.basic_qos(prefetch_count=1)
    updates = Queue()
    task = None
    executor = ThreadPoolExecutor(max_workers=1)

    def execute(job):
        def progress(value, message):
            updates.put((value, message))

        if kind == "generate":
            from services.ml.generation import generate

            return generate(
                job["config"], Path("/artifacts/datasets") / str(job["id"]), progress
            )
        from services.ml.training import train

        return train(
            job["config"],
            Path("/artifacts/datasets") / job["config"]["dataset_id"],
            Path("/artifacts/models") / str(job["id"]),
            progress,
        )

    def announce(job, progress, message, status):
        publish(
            channel,
            f"jobs.progress.{job['id']}",
            event(
                "job_progress",
                None,
                dict(
                    job_id=str(job["id"]),
                    progress=progress,
                    message=message,
                    status=status,
                ),
            ),
        )

    def receive(ch, method, properties, body):
        nonlocal task
        try:
            message = decode(body, "job_" + kind)
            job_id = str(UUID(message["payload"]["job_id"]))
            with connect() as conn:
                job = conn.execute(
                    "SELECT * FROM jobs WHERE id=%s AND kind=%s FOR UPDATE",
                    (job_id, kind),
                ).fetchone()
                if not job:
                    raise ValueError("Unknown job")
                if job["status"] in ("completed", "failed"):
                    ch.basic_ack(method.delivery_tag)
                    return
                if job["attempts"] >= 3:
                    conn.execute(
                        "UPDATE jobs SET status='failed',message='Limite de retomadas atingido',finished_at=now() WHERE id=%s",
                        (job_id,),
                    )
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    return
                conn.execute(
                    "UPDATE jobs SET status='running',progress=0,message='Iniciando',attempts=attempts+1,started_at=coalesce(started_at,now()) WHERE id=%s",
                    (job_id,),
                )
                audit(
                    conn,
                    "job_started",
                    job["user_id"],
                    details={"job_id": job_id, "kind": kind},
                )
            task = (job, method.delivery_tag, executor.submit(execute, job))
        except (ValueError, TypeError, KeyError):
            ch.basic_nack(method.delivery_tag, requeue=False)

    try:
        channel.basic_consume(queue_name, receive, auto_ack=False)
        while True:
            connection.process_data_events(time_limit=0.2)
            mark_healthy()
            if task is None:
                continue
            job, delivery_tag, future = task
            # Collapse bursts of fine-grained updates into one persistent status.
            update = None
            while True:
                try:
                    update = updates.get_nowait()
                except Empty:
                    break
            if update:
                value, message = update
                with connect() as conn:
                    conn.execute(
                        "UPDATE jobs SET progress=greatest(progress,%s),message=%s WHERE id=%s",
                        (value, message, job["id"]),
                    )
                announce(job, value, message, "running")
            if not future.done():
                continue
            error = future.exception()
            if error:
                message = f"Falha no processamento ({type(error).__name__}); consulte os logs do worker"
                log.error(
                    "Lab job %s failed (%s)",
                    job["id"],
                    type(error).__name__,
                    exc_info=(type(error), error, error.__traceback__),
                )
                with connect() as conn:
                    conn.execute(
                        "UPDATE jobs SET status='failed',message=%s,finished_at=now() WHERE id=%s",
                        (message, job["id"]),
                    )
                    audit(
                        conn,
                        "job_failed",
                        job["user_id"],
                        details={
                            "job_id": str(job["id"]),
                            "error_type": type(error).__name__,
                        },
                    )
                announce(job, 0, message, "failed")
                channel.basic_nack(delivery_tag, requeue=False)
            else:
                result = future.result()
                with connect() as conn:
                    if kind == "train":
                        conn.execute(
                            "SELECT pg_advisory_xact_lock(hashtext('active_model_version'))"
                        )
                        accepted = result["accepted"]
                        if accepted:
                            conn.execute(
                                "UPDATE model_versions SET active=false WHERE active"
                            )
                        conn.execute(
                            """INSERT INTO model_versions(id,job_id,dataset_id,accepted,active,metrics,artifact_path)
                            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                            (
                                job["id"],
                                job["id"],
                                job["config"]["dataset_id"],
                                accepted,
                                accepted,
                                Jsonb(result),
                                f"/artifacts/models/{job['id']}/models.joblib",
                            ),
                        )
                        if accepted:
                            audit(
                                conn,
                                "model_activated",
                                job["user_id"],
                                details={"model_id": str(job["id"]), "automatic": True},
                            )
                        stored = dict(
                            model_id=str(job["id"]),
                            accepted=accepted,
                            sample_counts=result["sample_counts"],
                        )
                    else:
                        stored = result
                    conn.execute(
                        "UPDATE jobs SET status='completed',progress=100,message='Concluído',result=%s,finished_at=now() WHERE id=%s",
                        (Jsonb(stored), job["id"]),
                    )
                    audit(
                        conn,
                        "job_completed",
                        job["user_id"],
                        details={"job_id": str(job["id"]), "kind": kind},
                    )
                announce(job, 100, "Concluído", "completed")
                channel.basic_ack(delivery_tag)
            task = None
    finally:
        executor.shutdown(wait=True)
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    kind = sys.argv[1]
    if kind not in ("generate", "train"):
        raise SystemExit("Expected generate or train")
    supervise(lambda: run(kind))
