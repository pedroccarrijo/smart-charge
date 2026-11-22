"""Local diagnostic CLI using the same authenticated, audited API as the Web."""

import argparse
from getpass import getpass
import json
from urllib.request import Request, urlopen

from services.common import DEVICES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("device", choices=DEVICES)
    parser.add_argument(
        "action",
        choices=["set_contactor", "set_occupied", "set_power_limit", "set_fault"],
    )
    parser.add_argument("value")
    parser.add_argument("--username", default="operador")
    args = parser.parse_args()
    if args.action in ("set_contactor", "set_occupied"):
        if args.value not in ("on", "off"):
            parser.error("This action requires on or off")
        value = args.value == "on"
    else:
        value = float(args.value)
        if not 0 <= value <= 100:
            parser.error("Expected percentage 0..100")

    def request(path, payload, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        with urlopen(
            Request(
                "http://api:8000" + path,
                data=json.dumps(payload).encode(),
                headers=headers,
            ),
            timeout=15,
        ) as response:
            return json.load(response)

    login = request(
        "/api/auth/login", dict(username=args.username, password=getpass("Senha: "))
    )
    token = login["access_token"]
    try:
        result = request(
            f"/api/devices/{args.device}/commands",
            dict(action=args.action, value=value),
            token,
        )
        print(result["id"])
    finally:
        request("/api/auth/logout", {}, token)


if __name__ == "__main__":
    main()
