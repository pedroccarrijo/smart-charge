from datetime import datetime
import math

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from services.common import decode, log, mark_healthy, rabbit, secret, supervise


def run():
    connection, channel = rabbit("writer")
    try:
        with InfluxDBClient(
            url="http://influxdb:8086",
            token=secret("influx_token"),
            org="smartcharge",
            timeout=10000,
        ) as influx:
            writer = influx.write_api(write_options=SYNCHRONOUS)

            def consume(ch, method, properties, body):
                try:
                    message = decode(body, "telemetry")
                    point = Point("charging_telemetry").tag(
                        "device_id", message["device_id"]
                    )
                    for name, value in message["payload"].items():
                        if isinstance(value, bool):
                            point.field(name, value)
                        elif type(value) in (int, float) and math.isfinite(value):
                            point.field(name, float(value))
                        elif isinstance(value, str):
                            point.field(name, value)
                    point.time(
                        datetime.fromisoformat(message["timestamp"]), WritePrecision.NS
                    )
                except (ValueError, KeyError, TypeError):
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    log.warning("Invalid telemetry sent to DLQ")
                    return
                try:
                    # Same device + timestamp overwrites on replay, making writes idempotent.
                    writer.write(bucket="telemetry", record=point)
                except Exception:
                    ch.basic_nack(method.delivery_tag, requeue=not method.redelivered)
                    raise
                ch.basic_ack(method.delivery_tag)

            channel.basic_consume("writer.telemetry", consume, auto_ack=False)
            while True:
                connection.process_data_events(time_limit=1)
                if influx.ping():
                    mark_healthy()
    finally:
        if connection.is_open:
            connection.close()


if __name__ == "__main__":
    supervise(run)
