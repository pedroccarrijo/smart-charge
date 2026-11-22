import os
import unittest
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
from pydantic import ValidationError
from api import assistant


class AssistantTests(unittest.TestCase):
    def test_local_only_configuration(self):
        for values in (
            {"OLLAMA_URL": "https://example.com:11434"},
            {"OLLAMA_URL": "http://ollama:invalid"},
            {"OLLAMA_MODEL": "model:cloud"},
        ):
            with patch.dict(os.environ, values), self.assertRaises(HTTPException):
                assistant.configuration()

    def test_question_bounds_and_no_tools(self):
        for value in ("  ", "x" * 1201):
            with self.assertRaises(ValidationError):
                assistant.Question(question=value)
        with self.assertRaises(ValidationError):
            assistant.Question(question="Olá", tools=["execute"])
        self.assertEqual(assistant.Question(question="  Olá  ").question, "Olá")

    def test_context_only_whitelisted_data_and_offline_values(self):
        points = [dict(device_id="ponto01", online=False, horario=None, telemetry=None)]
        state = dict(
            devices=[
                dict(device_id="ponto01", status="offline", health=None, rul_hours=None)
            ],
            alerts=[],
        )
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = None
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch.object(
                assistant.realtime, "snapshot", return_value={"pontos": points}
            ),
            patch.object(assistant.insights, "snapshot", return_value=state),
            patch.object(
                assistant.catalog,
                "snapshot",
                return_value={
                    "devices": [
                        {
                            "id": "ponto01",
                            "name": "Estação 01",
                            "password": "must-not-leak",
                        }
                    ]
                },
            ),
            patch.object(assistant, "connect", return_value=connection),
        ):
            context = assistant.context_summary()
        self.assertNotIn("must-not-leak", str(context))
        self.assertFalse(context["devices"][0]["online"])
        self.assertIsNone(context["devices"][0]["readings"]["voltage_v"])
        self.assertIsNone(context["devices"][0]["prediction"]["health"])
        self.assertIsNone(context["approved_model"])


class AssistantFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_model_finishes_and_releases_request(self):
        import httpx
        import json
        from unittest.mock import AsyncMock

        client = MagicMock()
        client.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("unavailable"))
        with (
            patch.object(assistant, "reserve", return_value="test-request"),
            patch.object(
                assistant,
                "context_summary",
                return_value={"snapshot_at": "now", "devices": []},
            ),
            patch.object(assistant, "messages_for", return_value=[]),
            patch.object(assistant, "finish") as finish,
            patch.object(assistant.httpx, "AsyncClient", return_value=client),
        ):
            response = await assistant.chat(
                assistant.Question(question="Estado atual?"), MagicMock(), {"id": 1}
            )
            events = [json.loads(item) async for item in response.body_iterator]
        self.assertEqual(events[-1]["type"], "error")
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[1], "failed")
        self.assertNotIn("unavailable", events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
