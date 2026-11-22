import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.common import secret

BASE = os.getenv("API_BASE", "http://frontend:8080")


def request(path, payload=None, token=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as response:
        return response.code, json.load(response)


def login(role):
    passwords = json.loads(secret("demo_users.json"))
    code, result = request(
        "/api/auth/login", dict(username=role, password=passwords[role])
    )
    assert code == 200, (role, code)
    return result["access_token"]
