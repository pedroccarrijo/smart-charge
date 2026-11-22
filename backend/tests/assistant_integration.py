"""Real Ollama streaming, authentication, audit, cancellation and concurrency."""

import json
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from api.db import connect
from tests.http_helpers import BASE, login, request


def stream(token, conversation, question):
    return urlopen(
        Request(
            BASE + "/api/assistant/chat",
            data=json.dumps(
                dict(question=question, conversation_id=conversation)
            ).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        ),
        timeout=160,
    )


def main():
    viewer, operator, admin = [
        login(role) for role in ("visualizador", "operador", "administrador")
    ]
    conversation = str(uuid4())
    fixture = str(uuid4())
    try:
        assert request("/api/assistant/status")[0] == 401
        for token in (viewer, operator, admin):
            code, status = request("/api/assistant/status", token=token)
            assert code == 200 and status["available"] and status["downloaded"], status
        assert request("/api/assistant/chat", {"question": " "}, viewer)[0] == 422
        with connect() as conn:
            commands_before = conn.execute(
                "SELECT count(*) AS n FROM command_outbox"
            ).fetchone()["n"]
        start = time.monotonic()
        with stream(
            viewer,
            conversation,
            "Resuma brevemente o estado atual das três estações. Há alertas ativos?",
        ) as response:
            events = []
            for line in response:
                event = json.loads(line)
                events.append(event)
                if event["type"] in ("context", "done", "error"):
                    print(
                        "Evento recebido:",
                        event["type"],
                        "após",
                        round(time.monotonic() - start, 1),
                        "s",
                        flush=True,
                    )
        assert events[0]["type"] == "status"
        assert any(e["type"] == "context" and e["online_devices"] == 3 for e in events)
        assert events[-1]["type"] == "done", events[-1]
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert len(tokens) > 2 and len("".join(tokens)) > 40
        print(
            "PASS: Ollama real respondeu em fluxo, com contexto das três estações:",
            "".join(tokens)[:900],
            flush=True,
        )
        deadline = time.monotonic() + 10
        while True:
            with connect() as conn:
                saved = conn.execute(
                    "SELECT status,answer FROM assistant_requests WHERE conversation_id=%s",
                    (conversation,),
                ).fetchone()
            if saved["status"] == "completed":
                break
            assert time.monotonic() < deadline
            time.sleep(0.2)
        assert saved["answer"] == "".join(tokens)
        with stream(
            viewer,
            conversation,
            "Explique detalhadamente toda a arquitetura e cada etapa do projeto.",
        ) as response:
            assert json.loads(response.readline())["type"] == "status"
            assert (
                request(
                    "/api/assistant/chat",
                    {"question": "Concorrência de teste"},
                    operator,
                )[0]
                == 409
            )
            # Closing the socket aborts streaming without leaving the global slot occupied.
        deadline = time.monotonic() + 15
        while True:
            with connect() as conn:
                running = conn.execute(
                    "SELECT count(*) AS n FROM assistant_requests WHERE conversation_id=%s AND status='running'",
                    (conversation,),
                ).fetchone()["n"]
            if not running:
                break
            assert time.monotonic() < deadline, "Cancelamento não liberou o assistente"
            time.sleep(0.3)
        print(
            "PASS: concorrência rejeitada e cancelamento libera o assistente",
            flush=True,
        )
        with connect() as conn:
            user_id = conn.execute(
                "SELECT id FROM users WHERE username='operador'"
            ).fetchone()["id"]
            for _ in range(5):
                conn.execute(
                    """INSERT INTO assistant_requests(id,conversation_id,user_id,question,answer,model,status,context_at,finished_at)
                    VALUES (%s,%s,%s,'Limite de teste','','test','failed',now(),now())""",
                    (uuid4(), fixture, user_id),
                )
        assert (
            request("/api/assistant/chat", {"question": "Teste de limite"}, operator)[0]
            == 429
        )
        with connect() as conn:
            assert (
                conn.execute("SELECT count(*) AS n FROM command_outbox").fetchone()["n"]
                == commands_before
            )
            actions = {
                row["action"]
                for row in conn.execute(
                    "SELECT action FROM audit_log WHERE details->>'conversation_id'=%s OR details->>'request_id' IN (SELECT id::text FROM assistant_requests WHERE conversation_id=%s)",
                    (conversation, conversation),
                ).fetchall()
            }
        assert {
            "assistant_question",
            "assistant_completed",
            "assistant_cancelled",
        } <= actions, actions
        print(
            "PASS: autenticação, três papéis, limites, auditoria e nenhuma alteração de atuadores",
            flush=True,
        )
    finally:
        with connect() as conn:
            conn.execute(
                "DELETE FROM assistant_requests WHERE conversation_id=%s", (fixture,)
            )
        for token in (viewer, operator, admin):
            request("/api/auth/logout", {}, token)


if __name__ == "__main__":
    main()
