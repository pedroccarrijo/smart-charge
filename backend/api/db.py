import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.common import secret


def connect():
    return psycopg.connect(
        host="postgres",
        dbname="smartcharge",
        user="smartcharge_app",
        password=secret("postgres_password"),
        row_factory=dict_row,
        connect_timeout=5,
    )


def audit(conn, action, user_id=None, device_id=None, details=None):
    conn.execute(
        "INSERT INTO audit_log(action,user_id,device_id,details) VALUES (%s,%s,%s,%s)",
        (action, user_id, device_id, Jsonb(details or {})),
    )
