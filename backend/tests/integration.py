"""Run inside API container; restores actuator states after end-to-end checks."""

import time
from tests.http_helpers import login, request

TOKEN = None


def status():
    code, rows = request("/api/status", token=TOKEN)
    assert code == 200
    return {row["device_id"]: row for row in rows}


def send(device, action, value):
    code, result = request(
        f"/api/devices/{device}/commands", dict(action=action, value=value), TOKEN
    )
    assert code == 202, result
    return result["id"]


def await_command(device, command_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        point = status()[device]
        if point["online"] and point["telemetry"].get("last_command_id") == command_id:
            return point["telemetry"]
        time.sleep(0.5)
    raise AssertionError(f"Command not observed: {device} {command_id}")


def main():
    global TOKEN
    TOKEN = login("operador")
    initial = status()
    assert len(initial) == 3 and all(point["online"] for point in initial.values())
    first = initial["ponto01"]["telemetry"]
    second = initial["ponto02"]["telemetry"]
    try:
        stopped = await_command("ponto01", send("ponto01", "set_contactor", False))
        assert stopped["contactor_on"] is False
        assert stopped["power_kw"] == stopped["current_a"] == 0
        assert stopped["estimated_minutes"] is None
        energy, battery = stopped["energy_kwh"], stopped["battery_percent"]
        time.sleep(2)
        stopped = status()["ponto01"]["telemetry"]
        assert stopped["energy_kwh"] == energy and stopped["battery_percent"] == battery
        print(
            "PASS: contator aberto zera corrente/potência e interrompe energia/bateria"
        )

        limited = await_command("ponto02", send("ponto02", "set_power_limit", 20))
        assert limited["requested_limit_percent"] == 20
        assert limited["power_kw"] <= 4.4
        print(
            "PASS: limite de potência enviado por RabbitMQ aparece na telemetria persistida"
        )
        if not initial["ponto03"]["telemetry"]["occupied"]:
            started = await_command("ponto03", send("ponto03", "set_occupied", True))
            ended = await_command("ponto03", send("ponto03", "set_occupied", False))
            assert ended["session_id"] == started["session_id"]
            code, sessions = request("/api/sessions", token=TOKEN)
            assert code == 200
            saved = next(row for row in sessions if row["id"] == started["session_id"])
            assert saved["status"] == "ended" and saved["ended_at"]
            print(
                "PASS: entrada e saída de veículo criam e encerram sessão no PostgreSQL"
            )
    finally:
        await_command(
            "ponto01", send("ponto01", "set_contactor", first["contactor_on"])
        )
        await_command(
            "ponto02",
            send("ponto02", "set_power_limit", second["requested_limit_percent"]),
        )
        print("Estados dos atuadores restaurados")
        request("/api/auth/logout", {}, TOKEN)


if __name__ == "__main__":
    main()
