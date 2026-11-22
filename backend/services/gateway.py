from queue import Queue, Empty, Full
from datetime import datetime, timezone
import threading

import paho.mqtt.client as mqtt

from services.common import (
    decode,
    log,
    mark_healthy,
    publish,
    rabbit,
    secret,
    supervise,
)


def run():
    incoming = Queue(maxsize=1000)
    connected = threading.Event()
    overflow = threading.Event()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="smartcharge-gateway",
        clean_session=False,
    )
    client.manual_ack_set(True)
    client.username_pw_set("gateway", secret("mqtt_password"))

    def on_connect(client, userdata, flags, code, properties):
        if code == 0:
            client.subscribe("smartcharge/+/telemetry", qos=1)
            connected.set()

    def on_disconnect(client, userdata, flags, code, properties):
        connected.clear()

    def on_message(client, userdata, message):
        try:
            incoming.put_nowait(message)
        except Full:
            # Reconnect the persistent session to redeliver unacknowledged packets.
            overflow.set()

    client.on_connect, client.on_disconnect, client.on_message = (
        on_connect,
        on_disconnect,
        on_message,
    )
    connection = None
    try:
        connection, channel = rabbit("gateway")
        client.connect("mosquitto", 1883, 30)
        client.loop_start()

        def command(ch, method, properties, body):
            try:
                message = decode(body, "command")
                if (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(message["timestamp"])
                ).total_seconds() > 30:
                    raise ValueError("Expired command")
                # Validation here sends invalid commands to DLQ instead of acknowledging them.
                from services.simulation import ChargingPoint

                ChargingPoint(0).command(message)
            except (ValueError, KeyError, TypeError):
                log.warning("Invalid command sent to DLQ")
                ch.basic_nack(method.delivery_tag, requeue=False)
                return
            info = client.publish(
                f"smartcharge/{message['device_id']}/commands", body, qos=1
            )
            info.wait_for_publish(timeout=10)
            if not info.is_published():
                raise ConnectionError("MQTT command not confirmed")
            ch.basic_ack(method.delivery_tag)
            log.info(
                "Command forwarded device=%s id=%s", message["device_id"], message["id"]
            )

        channel.basic_consume("gateway.commands", command, auto_ack=False)
        while True:
            if overflow.is_set():
                raise ConnectionError("MQTT backpressure")
            connection.process_data_events(time_limit=0.1)
            for _ in range(20):
                try:
                    message = incoming.get_nowait()
                except Empty:
                    break
                try:
                    data = decode(message.payload, "telemetry")
                    if message.topic != f"smartcharge/{data['device_id']}/telemetry":
                        raise ValueError("MQTT topic mismatch")
                except (ValueError, KeyError, TypeError):
                    log.warning("Invalid MQTT telemetry rejected")
                    client.ack(message.mid, message.qos)
                    continue
                publish(channel, f"telemetry.station.power.{data['device_id']}", data)
                # MQTT acknowledgment occurs only after RabbitMQ publisher confirmation.
                client.ack(message.mid, message.qos)
            if connected.is_set():
                mark_healthy()
    finally:
        client.disconnect()
        client.loop_stop()
        if connection and connection.is_open:
            connection.close()


if __name__ == "__main__":
    supervise(run)
