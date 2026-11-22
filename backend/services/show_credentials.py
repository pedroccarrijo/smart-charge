"""Explicit local operator command; secrets are never printed during startup."""

import json
from services.common import secret

if __name__ == "__main__":
    for username, password in json.loads(secret("demo_users.json")).items():
        print(f"{username}: {password}")
