from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

import bcrypt
from fastapi import Depends, HTTPException, Request, APIRouter
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, Field, field_validator

from api.db import connect, audit
from services.common import secret

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])
bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt())


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if len(value.encode()) > 72:
            raise ValueError("Senha excede 72 bytes")
        return value


def active_session(login_id):
    with connect() as conn:
        return conn.execute(
            """SELECT u.id,u.username,u.role,s.id AS login_id,s.expires_at
            FROM login_sessions s JOIN users u ON u.id=s.user_id
            WHERE s.id=%s AND NOT s.revoked AND s.expires_at>now() AND u.active""",
            (login_id,),
        ).fetchone()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    try:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ValueError("Missing bearer")
        payload = jwt.decode(
            credentials.credentials,
            secret("jwt_key"),
            algorithms=["HS256"],
            audience="smartcharge-web",
            issuer="smartcharge",
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        user = active_session(payload["jti"])
        if not user or str(user["id"]) != payload["sub"]:
            raise ValueError("Revoked session")
        return user
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            401, "Faça login novamente", headers={"WWW-Authenticate": "Bearer"}
        ) from None


def operator(user=Depends(current_user)):
    if user["role"] not in ("operador", "administrador"):
        raise HTTPException(403, "Seu papel permite apenas visualização")
    return user


def administrator(user=Depends(current_user)):
    if user["role"] != "administrador":
        raise HTTPException(403, "Acesso reservado ao administrador")
    return user


@router.post("/login")
def login(data: Login, request: Request):
    ip = request.client.host if request.client else "unknown"
    username = data.username.strip().lower()
    with connect() as conn:
        # Serialize attempts for both account and IP, including concurrent requests.
        for key in sorted(("ip:" + ip, "user:" + username)):
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
        counts = conn.execute(
            """SELECT count(*) FILTER(WHERE username=%s) AS account,
            count(*) FILTER(WHERE ip=%s) AS address FROM login_attempts
            WHERE NOT success AND created_at>now()-interval '5 minutes' """,
            (username, ip),
        ).fetchone()
        if counts["account"] >= 5 or counts["address"] >= 20:
            audit(conn, "login_limited", details={"username": username, "ip": ip})
            error = 429
        else:
            user = conn.execute(
                "SELECT * FROM users WHERE username=%s", (username,)
            ).fetchone()
            valid = bcrypt.checkpw(
                data.password.encode(),
                user["password_hash"].encode() if user else DUMMY_HASH,
            )
            success = bool(user and user["active"] and valid)
            conn.execute(
                "INSERT INTO login_attempts(username,ip,success) VALUES (%s,%s,%s)",
                (username, ip, success),
            )
            audit(
                conn,
                "login_success" if success else "login_failure",
                user["id"] if user else None,
                details={"username": username, "ip": ip},
            )
            error = None if success else 401
            if success:
                login_id = str(uuid4())
                expires = datetime.now(timezone.utc) + timedelta(hours=1)
                conn.execute(
                    "INSERT INTO login_sessions(id,user_id,expires_at) VALUES (%s,%s,%s)",
                    (login_id, user["id"], expires),
                )
    # Raise outside the transaction, preserving failed attempts and audit records.
    if error:
        raise HTTPException(
            error,
            "Aguarde 5 minutos para tentar novamente"
            if error == 429
            else "Usuário ou senha inválidos",
            headers={"Retry-After": "300"} if error == 429 else {},
        )
    token = jwt.encode(
        dict(
            sub=str(user["id"]),
            jti=login_id,
            iat=datetime.now(timezone.utc),
            exp=expires,
            iss="smartcharge",
            aud="smartcharge-web",
        ),
        secret("jwt_key"),
        algorithm="HS256",
    )
    return dict(
        access_token=token,
        token_type="bearer",
        user=dict(username=user["username"], role=user["role"]),
    )


@router.get("/me")
def me(user=Depends(current_user)):
    return dict(username=user["username"], role=user["role"])


@router.post("/logout")
def logout(user=Depends(current_user)):
    with connect() as conn:
        conn.execute(
            "UPDATE login_sessions SET revoked=true WHERE id=%s", (user["login_id"],)
        )
        audit(conn, "logout", user["id"])
    return {"status": "ok"}


@router.post("/ws-ticket")
def ticket(user=Depends(current_user)):
    raw = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute(
            "DELETE FROM ws_tickets WHERE expires_at<now()-interval '1 minute'"
        )
        conn.execute(
            "INSERT INTO ws_tickets(ticket_hash,login_id,expires_at) VALUES (%s,%s,now()+interval '30 seconds')",
            (hashlib.sha256(raw.encode()).hexdigest(), user["login_id"]),
        )
    return {"ticket": raw, "expires_in": 30}


def consume_ticket(raw):
    if not raw or len(raw) > 100:
        return None
    with connect() as conn:
        record = conn.execute(
            """UPDATE ws_tickets SET used_at=now() WHERE ticket_hash=%s
            AND used_at IS NULL AND expires_at>now() RETURNING login_id""",
            (hashlib.sha256(raw.encode()).hexdigest(),),
        ).fetchone()
    return active_session(record["login_id"]) if record else None
