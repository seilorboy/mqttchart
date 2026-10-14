"""Raw MQTT archive and browser view. Run one instance per MQTT client ID."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
import time

from flask import Flask, jsonify, render_template, request
import mysql.connector
import paho.mqtt.client as mqtt
from waitress import serve

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
state = {"mqtt_connected": False, "subscribed": False}


@contextmanager
def database():
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"], database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        connection_timeout=5,
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with database() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mqtt_messages (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    received_at DATETIME(6) NOT NULL COMMENT 'UTC reception time',
                    topic TEXT NOT NULL,
                    payload LONGBLOB NOT NULL,
                    qos TINYINT UNSIGNED NOT NULL,
                    retained BOOLEAN NOT NULL,
                    INDEX idx_received_at (received_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()


def on_connect(client, userdata, flags, reason_code, properties):
    state.update(mqtt_connected=not reason_code.is_failure, subscribed=False)
    if reason_code.is_failure:
        log.error("MQTT connection rejected: %s", reason_code)
        return
    client.subscribe(os.environ.get("MQTT_TOPIC", "han/#"), qos=1)


def on_subscribe(client, userdata, mid, reason_codes, properties):
    state["subscribed"] = bool(reason_codes) and all(not code.is_failure for code in reason_codes)
    log.info("MQTT subscription accepted: %s", state["subscribed"])


def on_disconnect(client, userdata, flags, reason_code, properties):
    state.update(mqtt_connected=False, subscribed=False)
    log.warning("MQTT disconnected: %s", reason_code)


def on_message(client, userdata, message):
    received_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with database() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO mqtt_messages (received_at, topic, payload, qos, retained) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (received_at, message.topic, message.payload, message.qos, message.retain),
                )
            conn.commit()
    except mysql.connector.Error:
        log.exception("MQTT storage failed; restarting without acknowledging the message")
        # Restart the container to reconnect the persistent MQTT session. QoS 0
        # cannot be recovered; QoS 1 is acknowledged only after a successful commit.
        os._exit(1)
    if message.qos:
        client.ack(message.mid, message.qos)


def serialize(row):
    row = dict(row)
    row["received_at"] = row["received_at"].replace(tzinfo=timezone.utc).isoformat()
    try:
        row["payload"] = row["payload"].decode("utf-8")
        row["encoding"] = "utf-8"
    except UnicodeDecodeError:
        row["payload"] = base64.b64encode(row["payload"]).decode("ascii")
        row["encoding"] = "base64"
    return row


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/messages")
def messages():
    try:
        limit = min(500, max(1, int(request.args.get("limit", "100"))))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    with database() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute("SELECT * FROM mqtt_messages ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    return jsonify(messages=[serialize(row) for row in rows], **state)


@app.get("/health")
def health():
    with database() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return jsonify(database=True, **state)


@app.errorhandler(mysql.connector.Error)
def database_error(error):
    log.error("Database request failed: %s", type(error).__name__)
    return jsonify(error="Tietokantayhteys ei ole käytettävissä"), 503


def main():
    for attempt in range(30):
        try:
            init_db()
            break
        except mysql.connector.Error:
            if attempt == 29:
                raise
            time.sleep(2)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=os.environ.get("MQTT_CLIENT_ID", "han-mqtt-storage"),
        clean_session=False, manual_ack=True,
    )
    if os.environ.get("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD", ""))
    if os.environ.get("MQTT_TLS", "false").lower() == "true":
        client.tls_set()
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    client.connect_async(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")), 60)
    client.loop_start()
    try:
        serve(app, host="0.0.0.0", port=5000)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
