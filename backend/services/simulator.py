import json
from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
from queue import Queue, Empty
import random
import time

import paho.mqtt.client as mqtt

from services.common import DEVICES, decode, event, log, mark_healthy, secret, supervise
from services.simulation import ChargingPoint


def run():
    commands = Queue(maxsize=100)
    clients = []
    state = Path("/state/points.json")
    points = (
        [ChargingPoint(**row) for row in json.loads(state.read_text())]
        if state.exists()
        else [
            ChargingPoint(i, battery_percent=20 + i * 15, occupied=i != 3)
            for i in range(1, 4)
        ]
    )
    connected = set()
    rng = random.Random(int(os.getenv("SIMULATION_SEED", "42")))
    interval = float(os.getenv("SIMULATION_INTERVAL", "1"))
    if not 0.2 <= interval <= 60:
        raise ValueError("SIMULATION_INTERVAL must be between 0.2 and 60 seconds")

    def on_connect(client, device, flags, code, properties):
        if code == 0:
            client.subscribe(f"smartcharge/{device}/commands", qos=1)
            connected.add(device)

    def on_disconnect(client, device, flags, code, properties):
        connected.discard(device)

    def on_message(client, device, message):
        try:
            command = decode(message.payload, "command")
            if (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(command["timestamp"])
            ).total_seconds() > 30:
                raise ValueError("Expired command")
            if command["device_id"] != device:
                raise ValueError("Device mismatch")
            commands.put_nowait((device, command))
        except Exception as exc:
            log.warning("Simulator rejected command (%s)", type(exc).__name__)

    try:
        for device in DEVICES:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"simulator-{device}",
                userdata=device,
            )
            client.username_pw_set(device, secret("mqtt_" + device))
            client.on_connect, client.on_disconnect, client.on_message = (
                on_connect,
                on_disconnect,
                on_message,
            )
            client.max_queued_messages_set(20)
            client.connect("mosquitto", 1883, 30)
            client.loop_start()
            clients.append(client)
        previous = time.monotonic()
        while True:
            started = time.monotonic()
            seconds, previous = min(started - previous, max(5, interval * 2)), started
            while True:
                try:
                    device, command = commands.get_nowait()
                except Empty:
                    break
                try:
                    points[DEVICES.index(device)].command(command)
                    log.info("Command applied device=%s id=%s", device, command["id"])
                except (ValueError, KeyError) as exc:
                    log.warning("Invalid command payload (%s)", type(exc).__name__)
            readings = [point.step(seconds, rng) for point in points]
            temporary = state.with_suffix(".tmp")
            with temporary.open("w") as output:
                json.dump([asdict(point) for point in points], output)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(state)
            for device, payload, client in zip(DEVICES, readings, clients):
                if device in connected:
                    client.publish(
                        f"smartcharge/{device}/telemetry",
                        json.dumps(event("telemetry", device, payload)),
                        qos=1,
                    )
            if len(connected) == 3:
                mark_healthy()
            time.sleep(max(0.01, interval - (time.monotonic() - started)))
    finally:
        for client in clients:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    supervise(run)
