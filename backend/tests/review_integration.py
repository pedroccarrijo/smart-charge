"""Delivery review: persisted rules and bounded sensor history through Nginx."""

from tests.http_helpers import login, request


def main():
    assert request("/api/rules")[0] == 401
    assert request("/api/telemetry/history?device_id=ponto01")[0] == 401
    for role in ("visualizador", "operador", "administrador"):
        token = login(role)
        try:
            code, rules = request("/api/rules", token=token)
            assert code == 200 and any(
                row["id"] == "thermal_protection"
                and row["parameters"]["activate_at_c"] == 65
                for row in rules
            )
            code, history = request(
                "/api/telemetry/history?device_id=ponto01&minutes=30", token=token
            )
            assert code == 200 and 0 < len(history["readings"]) <= 181, history
            assert all(
                "temperature_c" in row and "current_a" in row and "voltage_v" in row
                for row in history["readings"]
            )
            assert history["readings"] == sorted(
                history["readings"], key=lambda row: row["timestamp"]
            )
            for path in (
                "/api/telemetry/history?device_id=unknown",
                "/api/telemetry/history?device_id=ponto01&minutes=999999",
            ):
                assert request(path, token=token)[0] == 422
        finally:
            request("/api/auth/logout", {}, token)
    print(
        "PASS: regras persistidas, histórico de temperatura/corrente/tensão, três papéis e limites da consulta"
    )


if __name__ == "__main__":
    main()
