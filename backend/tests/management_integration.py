import json
import time
from urllib.parse import urlparse

from websockets.sync.client import connect as websocket_connect

from tests.http_helpers import BASE, login, request


def device_body(row):
    return {
        key: row[key]
        for key in ("name", "location", "description", "commands_enabled", "revision")
    }


def component_body(row):
    return {
        key: row[key]
        for key in (
            "name",
            "normal_min",
            "normal_max",
            "critical_min",
            "critical_max",
            "revision",
        )
    }


def main():
    viewer, operator, admin = [
        login(role) for role in ("visualizador", "operador", "administrador")
    ]
    _, catalog = request("/api/catalog", token=admin)
    original_device = next(row for row in catalog["devices"] if row["id"] == "ponto03")
    original_sensor = next(
        row for row in catalog["components"] if row["id"] == "ponto01.temperature"
    )
    try:
        assert len(catalog["devices"]) == 3 and len(catalog["components"]) == 18
        for token in (viewer, operator):
            assert (
                request(
                    "/api/catalog/devices/ponto03",
                    device_body(original_device),
                    token,
                    "PUT",
                )[0]
                == 403
            )
        assert request("/api/messaging")[0] == 401
        deadline = time.monotonic() + 30
        while True:
            code, bus = request("/api/messaging", token=viewer)
            assert code == 200
            if bus["available"] and bus["recent"]:
                break
            assert time.monotonic() < deadline, bus.get("error")
            time.sleep(1)
        assert len(bus["queues"]) == 7 and len(bus["consumers"]) >= 6
        assert bus["rates"]["publish_in"] >= 0
        assert request("/api/messaging/dlq/peek", {}, viewer)[0] == 403
        code, first = request("/api/messaging/dlq/peek", {}, operator)
        assert code == 200 and first["preserved"]
        code, second = request("/api/messaging/dlq/peek", {}, admin)
        assert code == 200 and second["preserved"]
        if first["messages"]:
            assert first["messages"][0]["payload"] in [
                message["payload"] for message in second["messages"]
            ]
        print(
            "PASS: filas, taxas, consumidores e mensagens recentes; DLQ inspecionada e preservada",
            flush=True,
        )

        changed = {
            **device_body(original_device),
            "name": "Ponto de validação",
            "location": "Laboratório",
            "commands_enabled": False,
        }
        code, saved = request("/api/catalog/devices/ponto03", changed, admin, "PUT")
        assert code == 200, saved
        assert (
            request(
                "/api/devices/ponto03/commands",
                {"action": "set_contactor", "value": False},
                operator,
            )[0]
            == 423
        )
        assert request("/api/catalog/devices/ponto03", changed, admin, "PUT")[0] == 409
        invalid = {**component_body(original_sensor), "normal_min": 100}
        assert (
            request(
                "/api/catalog/components/ponto01.temperature", invalid, admin, "PUT"
            )[0]
            == 422
        )
        changed_sensor = {**component_body(original_sensor), "normal_max": 30}
        code, sensor = request(
            "/api/catalog/components/ponto01.temperature", changed_sensor, admin, "PUT"
        )
        assert code == 200, sensor
        _, ticket = request("/api/auth/ws-ticket", {}, viewer)
        with websocket_connect(
            "ws://" + urlparse(BASE).netloc + "/api/ws", origin=BASE
        ) as ws:
            ws.send(json.dumps(ticket))
            frame = json.loads(ws.recv(timeout=10))
            assert any(
                row["id"] == "ponto03" and not row["commands_enabled"]
                for row in frame["catalog"]["devices"]
            )
            assert any(
                row["id"] == "ponto01.temperature" and row["normal_max"] == 30
                for row in frame["catalog"]["components"]
            )
            assert any(
                row["device_id"] == "ponto03" and not row["commands_enabled"]
                for row in frame["pontos"]
            )
            assert frame["messaging"]["available"]
        print(
            "PASS: cadastro e faixas persistidos, conflitos de edição detectados e mudanças entregues por WebSocket",
            flush=True,
        )
        _, rows = request("/api/audit", token=admin)
        actions = {row["action"] for row in rows}
        assert {"device_updated", "component_updated", "dlq_inspected"} <= actions
        print(
            "PASS: três papéis respeitados, comandos bloqueados e alterações auditadas",
            flush=True,
        )
    finally:
        _, current = request("/api/catalog", token=admin)
        latest_device = next(
            row for row in current["devices"] if row["id"] == "ponto03"
        )
        latest_sensor = next(
            row for row in current["components"] if row["id"] == "ponto01.temperature"
        )
        assert (
            request(
                "/api/catalog/devices/ponto03",
                {**device_body(original_device), "revision": latest_device["revision"]},
                admin,
                "PUT",
            )[0]
            == 200
        )
        assert (
            request(
                "/api/catalog/components/ponto01.temperature",
                {
                    **component_body(original_sensor),
                    "revision": latest_sensor["revision"],
                },
                admin,
                "PUT",
            )[0]
            == 200
        )
        for token in (viewer, operator, admin):
            request("/api/auth/logout", {}, token)
        print("Cadastros e faixas originais restaurados", flush=True)


if __name__ == "__main__":
    main()
