import json
import time
from urllib.parse import urlparse

from websockets.sync.client import connect as websocket_connect

from tests.http_helpers import BASE, login, request


def wait_for(token, predicate, timeout=120):
    deadline, printed = time.monotonic() + timeout, 0
    while time.monotonic() < deadline:
        code, data = request("/api/insights", token=token)
        assert code == 200
        if predicate(data):
            return data
        if time.monotonic() - printed > 15:
            p = next((p for p in data["devices"] if p["device_id"] == "ponto03"), {})
            print(
                f"Insights: {p.get('status')} saúde={p.get('health')} RUL={p.get('rul_hours')} nível={p.get('level')}",
                flush=True,
            )
            printed = time.monotonic()
        time.sleep(1)
    raise AssertionError("Inference condition not reached")


def main():
    admin, viewer = login("administrador"), login("visualizador")
    initial = None
    deadline = time.monotonic() + 60
    while initial is None and time.monotonic() < deadline:
        _, points = request("/api/status", token=admin)
        initial = next(
            row["telemetry"] for row in points if row["device_id"] == "ponto03"
        )
        if initial is None:
            time.sleep(1)
    assert initial is not None, "Simulador ainda não enviou dados"
    _, lab = request("/api/lab", token=admin)
    active = next(row for row in lab["models"] if row["active"])

    def command(action, value):
        code, result = request(
            "/api/devices/ponto03/commands", dict(action=action, value=value), admin
        )
        assert code == 202, result
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, rows = request("/api/status", token=admin)
            p = next(row["telemetry"] for row in rows if row["device_id"] == "ponto03")
            if p and p.get("last_command_id") == result["id"]:
                return
            time.sleep(0.5)
        raise AssertionError("Command not applied")

    def point(data):
        return next(p for p in data["devices"] if p["device_id"] == "ponto03")

    try:
        assert request(f"/api/lab/models/{active['id']}/activate", {}, viewer)[0] == 403
        alternatives = [
            row
            for row in lab["models"]
            if row["accepted"] and row["id"] != active["id"]
        ]
        if alternatives:
            other = alternatives[0]
            assert (
                request(f"/api/lab/models/{other['id']}/activate", {}, admin)[0] == 200
            )
            wait_for(
                admin,
                lambda data: any(
                    p.get("model_id") == other["id"] for p in data["devices"]
                ),
                20,
            )
            assert (
                request(f"/api/lab/models/{active['id']}/activate", {}, admin)[0] == 200
            )
            wait_for(
                admin,
                lambda data: any(
                    p.get("model_id") == active["id"] for p in data["devices"]
                ),
                20,
            )
            print(
                "PASS: troca e restauração de versão sem reiniciar a inferência",
                flush=True,
            )
        command("set_occupied", True)
        command("set_contactor", True)
        command("set_power_limit", 100)
        command("set_fault", 0)
        baseline = wait_for(admin, lambda data: point(data).get("status") == "ready")
        baseline_health = point(baseline)["health"]
        print(f"Saúde inicial: {baseline_health:.2f}", flush=True)
        command("set_fault", 100)
        degraded = wait_for(
            admin,
            lambda data: point(data).get("health") is not None
            and point(data)["health"] < baseline_health - 15
            and any(
                a["device_id"] == "ponto03" and a["active"] for a in data["alerts"]
            ),
        )
        print(
            f"PASS: falha reduziu saúde para {point(degraded)['health']:.2f}, RUL={point(degraded)['rul_hours']:.2f} h e gerou alerta persistido",
            flush=True,
        )
        _, ticket = request("/api/auth/ws-ticket", {}, viewer)
        with websocket_connect(
            "ws://" + urlparse(BASE).netloc + "/api/ws", origin=BASE
        ) as ws:
            ws.send(json.dumps(ticket))
            snapshot = json.loads(ws.recv(timeout=10))
            assert snapshot["insights"]["alerts"]
            assert point(snapshot["insights"])["health"] is not None
        print("PASS: previsão e alerta entregues ao WebSocket autenticado", flush=True)
        command("set_fault", 0)
        wait_for(
            admin,
            lambda data: point(data).get("health") is not None
            and not any(
                a["device_id"] == "ponto03" and a["active"] for a in data["alerts"]
            ),
            180,
        )
        print("PASS: recuperação confirmou histerese e encerrou o alerta", flush=True)
    finally:
        command("set_fault", 0)
        command("set_power_limit", initial["requested_limit_percent"])
        command("set_contactor", initial["contactor_on"])
        command("set_occupied", initial["occupied"])
        request(f"/api/lab/models/{active['id']}/activate", {}, admin)
        request("/api/auth/logout", {}, admin)
        request("/api/auth/logout", {}, viewer)


if __name__ == "__main__":
    main()
