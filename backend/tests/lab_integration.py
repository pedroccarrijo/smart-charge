"""Generate one million rows and train both models via the authenticated API."""

import math
import time

from tests.http_helpers import login, request


def await_job(token, job_id, timeout=1200):
    deadline, previous = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        code, state = request("/api/lab", token=token)
        assert code == 200
        job = next(job for job in state["jobs"] if job["id"] == job_id)
        progress = (job["status"], int(job["progress"]) // 10)
        if progress != previous:
            print(
                f"{job['kind']}: {job['status']} {job['progress']:.1f}% — {job['message']}",
                flush=True,
            )
            previous = progress
        if job["status"] == "failed":
            raise AssertionError(job["message"])
        if job["status"] == "completed":
            return job, state
        time.sleep(2)
    raise AssertionError("Job timed out")


def main():
    viewer, operator, admin = [
        login(role) for role in ("visualizador", "operador", "administrador")
    ]
    try:
        assert request("/api/lab/generate", {}, viewer)[0] == 403
        assert request("/api/lab/generate", {}, operator)[0] == 403
        assert request("/api/lab/generate", {"rows": 999999}, admin)[0] == 422
        assert request("/api/lab/generate", {"rows": 3000001}, admin)[0] == 422
        code, submitted = request("/api/lab/generate", {}, admin)
        assert code == 202, submitted
        assert request("/api/lab/generate", {}, admin)[0] == 409
        generated, _ = await_job(admin, submitted["id"])
        assert generated["result"]["rows"] == 1_000_000
        assert generated["result"]["sensor_readings"] == 3_000_000
        print(
            "PASS: um milhão de leituras, três milhões de medições e controles de acesso/volume"
        )
        code, submitted = request(
            "/api/lab/train", {"dataset_id": generated["id"]}, admin
        )
        assert code == 202, submitted
        trained, state = await_job(admin, submitted["id"])
        model = next(
            model for model in state["models"] if model["job_id"] == trained["id"]
        )
        assert model["accepted"] and model["active"]
        for target, metrics in model["metrics"]["targets"].items():
            assert metrics["beats_baseline"]
            assert all(math.isfinite(value) for value in metrics["test"].values())
            print(
                f"PASS {target}: MAE={metrics['test']['mae']:.3f}; RMSE={metrics['test']['rmse']:.3f}; R²={metrics['test']['r2']:.3f}; baseline MAE={metrics['baseline']['mae']:.3f}"
            )
        groups = list(map(set, model["metrics"]["equipment_split"].values()))
        assert all(
            not left & right
            for i, left in enumerate(groups)
            for right in groups[i + 1 :]
        )
        print("PASS: versão aprovada e divisão por equipamentos sem sobreposição")
    finally:
        for token in (viewer, operator, admin):
            request("/api/auth/logout", {}, token)


if __name__ == "__main__":
    main()
