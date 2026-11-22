"""One-shot schema and demo-user initialization; never print credentials."""

import json
from pathlib import Path

import bcrypt
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from services.rules import THERMAL_PROTECTION

from api.db import connect
from services.common import DEVICES, secret


def main():
    with psycopg.connect(
        host="postgres",
        dbname="smartcharge",
        user="smartcharge",
        password=secret("postgres_admin_password"),
        autocommit=True,
    ) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='smartcharge_app'"
        ).fetchone()
        if not exists:
            admin.execute(
                sql.SQL(
                    "CREATE ROLE smartcharge_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                ).format(sql.Literal(secret("postgres_password")))
            )
        admin.execute("GRANT CONNECT ON DATABASE smartcharge TO smartcharge_app")
        admin.execute("GRANT USAGE, CREATE ON SCHEMA public TO smartcharge_app")
    with connect() as conn:
        conn.execute(Path("/app/api/schema.sql").read_text())
        conn.execute(
            """INSERT INTO automation_rules(id,name,description,parameters,execution_location)
            VALUES ('thermal_protection','Proteção térmica',%s,%s,'simulator')
            ON CONFLICT(id) DO UPDATE SET parameters=EXCLUDED.parameters,description=EXCLUDED.description,updated_at=now()""",
            (
                "Limita a potência a 30% em 65 °C; libera em 55 °C.",
                Jsonb(THERMAL_PROTECTION),
            ),
        )
        for device in DEVICES:
            conn.execute(
                "INSERT INTO devices(id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (device, "Estação " + device[-2:]),
            )
            components = [
                (
                    "temperature",
                    "Sensor de temperatura",
                    "sensor",
                    "temperature_c",
                    -10,
                    55,
                    -20,
                    65,
                ),
                ("current", "Sensor de corrente", "sensor", "current_a", 0, 35, 0, 45),
                (
                    "voltage",
                    "Sensor de tensão",
                    "sensor",
                    "voltage_v",
                    380,
                    420,
                    360,
                    440,
                ),
                (
                    "contactor",
                    "Contator",
                    "actuator",
                    "contactor_on",
                    None,
                    None,
                    None,
                    None,
                ),
                (
                    "limiter",
                    "Limitador de potência",
                    "actuator",
                    "power_limit_percent",
                    None,
                    None,
                    None,
                    None,
                ),
                (
                    "module",
                    "Módulo de potência",
                    "equipment",
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            ]
            for (
                suffix,
                name,
                kind,
                key,
                low,
                high,
                critical_low,
                critical_high,
            ) in components:
                conn.execute(
                    """INSERT INTO device_components(id,device_id,name,kind,telemetry_key,normal_min,normal_max,critical_min,critical_max)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (
                        f"{device}.{suffix}",
                        device,
                        name,
                        kind,
                        key,
                        low,
                        high,
                        critical_low,
                        critical_high,
                    ),
                )
        for role, password in json.loads(secret("demo_users.json")).items():
            if not conn.execute(
                "SELECT 1 FROM users WHERE username=%s", (role,)
            ).fetchone():
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    "INSERT INTO users(username,password_hash,role) VALUES (%s,%s,%s)",
                    (role, hashed, role),
                )
    print("Banco inicializado; três papéis disponíveis. Nenhuma senha exibida.")


if __name__ == "__main__":
    main()
