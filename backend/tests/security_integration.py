import json
import hashlib
from urllib.parse import urlparse

from websockets.sync.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosedError

from api.db import connect
from tests.http_helpers import BASE, login, request


def closed_with_policy(ws):
    try:
        for _ in range(5):
            ws.recv(timeout=5)
    except ConnectionClosedError as exc:
        assert exc.rcvd.code == 1008
        return
    raise AssertionError("WebSocket should have closed")


def main():
    viewer, operator, admin = [
        login(role) for role in ("visualizador", "operador", "administrador")
    ]
    try:
        assert request("/api/status")[0] == 401
        assert request("/api/status", token=viewer)[0] == 200
        assert (
            request(
                "/api/devices/ponto01/commands",
                {"action": "set_contactor", "value": False},
                viewer,
            )[0]
            == 403
        )
        assert request("/api/audit", token=operator)[0] == 403
        assert request("/api/audit", token=admin)[0] == 200
        assert (
            request(
                "/api/devices/ponto01/commands",
                {"action": "set_contactor", "value": "false"},
                operator,
            )[0]
            == 422
        )
        parts = viewer.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        assert request("/api/status", token=".".join(parts))[0] == 401
        print("PASS: JWT obrigatório, assinatura validada e três papéis respeitados")

        code, ticket = request("/api/auth/ws-ticket", {}, viewer)
        assert code == 200
        ws_url = "ws://" + urlparse(BASE).netloc + "/api/ws"
        with websocket_connect(ws_url, origin=BASE) as ws:
            ws.send(json.dumps(ticket))
            snapshot = json.loads(ws.recv(timeout=10))
            assert len(snapshot["pontos"]) == 3 and snapshot["consumer_online"]
            assert snapshot["sessions"]
            with websocket_connect(ws_url, origin=BASE) as replay:
                replay.send(json.dumps(ticket))
                closed_with_policy(replay)
            request("/api/auth/logout", {}, viewer)
            closed_with_policy(ws)
        assert request("/api/status", token=viewer)[0] == 401
        print(
            "PASS: WebSocket entrega dados, ticket tem uso único e logout revoga conexão/token"
        )

        _, expired = request("/api/auth/ws-ticket", {}, operator)
        with connect() as conn:
            conn.execute(
                "UPDATE ws_tickets SET expires_at=now()-interval '1 second' WHERE ticket_hash=%s",
                (hashlib.sha256(expired["ticket"].encode()).hexdigest(),),
            )
        with websocket_connect(ws_url, origin=BASE) as ws:
            ws.send(json.dumps(expired))
            closed_with_policy(ws)
        print("PASS: ticket expirado rejeitado")

        for _ in range(5):
            assert (
                request(
                    "/api/auth/login",
                    {"username": "limite_teste", "password": "senha_invalida"},
                )[0]
                == 401
            )
        assert (
            request(
                "/api/auth/login",
                {"username": "limite_teste", "password": "senha_invalida"},
            )[0]
            == 429
        )
        print("PASS: tentativas de login limitadas e persistidas")
        with connect() as conn:
            actions = {
                row["action"]
                for row in conn.execute(
                    "SELECT DISTINCT action FROM audit_log"
                ).fetchall()
            }
            assert {
                "login_success",
                "login_failure",
                "login_limited",
                "logout",
            } <= actions
            assert not conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper"
            ).fetchone()
        print(
            "PASS: auditoria registrada e conta PostgreSQL da aplicação sem superusuário"
        )
    finally:
        for token in (viewer, operator, admin):
            request("/api/auth/logout", {}, token)
        with connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE username='limite_teste'")


if __name__ == "__main__":
    main()
