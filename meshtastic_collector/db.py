import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

import psycopg2
from psycopg2 import OperationalError, Binary
from psycopg2.extras import Json


class Database:
    """PostgreSQL helper for Meshtastic MQTT ingestion."""

    def __init__(self):
        self.host = os.environ.get("POSTGRES_HOST", "localhost")
        self.port = int(os.environ.get("POSTGRES_PORT", "5432"))
        self.database = self._require_env("POSTGRES_DB")
        self.user = self._require_env("POSTGRES_USER")
        self.password = self._require_env("POSTGRES_PASSWORD")
        self._conn = None
        self._lock = threading.Lock()

    @staticmethod
    def _require_env(key: str) -> str:
        value = os.environ.get(key)
        if not value:
            raise ValueError(f"Environment variable {key} must be set for database connectivity")
        return value

    def connect(self) -> None:
        if self._conn and not self._conn.closed:
            return

        self._conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
        )
        self._conn.autocommit = True

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def ensure_schema(self) -> None:
        """Create tables if they don't already exist."""

        ddl = """
        CREATE TABLE IF NOT EXISTS devices (
            node_id TEXT PRIMARY KEY,
            display_name TEXT,
            hw_model TEXT,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS gateways (
            gateway_id TEXT PRIMARY KEY,
            name TEXT,
            location_lat DOUBLE PRECISION,
            location_lon DOUBLE PRECISION,
            location_alt DOUBLE PRECISION,
            installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS positions (
            id SERIAL PRIMARY KEY,
            ts_utc TIMESTAMPTZ NOT NULL,
            node_id TEXT NOT NULL,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            alt DOUBLE PRECISION,
            speed REAL,
            heading REAL,
            accuracy REAL,
            battery_v REAL,
            rssi INTEGER,
            snr REAL,
            seq_no BIGINT,
            hop_limit INTEGER,
            gateway_id TEXT,
            channel_id TEXT,
            msg_id TEXT,
            raw_payload JSONB,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_positions_node_time ON positions(node_id, ts_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_positions_msg ON positions(node_id, seq_no, msg_id);

        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            ts_utc TIMESTAMPTZ NOT NULL,
            node_id TEXT NOT NULL,
            to_node TEXT,
            channel_id TEXT,
            text_body TEXT,
            rx_time TIMESTAMPTZ,
            rssi INTEGER,
            snr REAL,
            hop_limit INTEGER,
            msg_id TEXT,
            seq_no BIGINT,
            gateway_id TEXT,
            raw_payload JSONB,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_messages_node_time ON messages(node_id, ts_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_msg ON messages(node_id, seq_no, msg_id);

        CREATE TABLE IF NOT EXISTS raw_packets (
            id SERIAL PRIMARY KEY,
            topic TEXT NOT NULL,
            payload BYTEA NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_raw_topic_time ON raw_packets(topic, recorded_at DESC);
        """

        self._execute(ddl, ())
        self._execute(
            "ALTER TABLE IF EXISTS gateways ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            (),
        )

    def upsert_device(self, node_id: str, display_name: Optional[str], hw_model: Optional[str]) -> None:
        query = """
            INSERT INTO devices (node_id, display_name, hw_model, last_seen)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (node_id) DO UPDATE
            SET display_name = COALESCE(EXCLUDED.display_name, devices.display_name),
                hw_model = COALESCE(EXCLUDED.hw_model, devices.hw_model),
                last_seen = NOW();
        """
        self._execute(query, (node_id, display_name, hw_model))

    def save_position(self, node_id: str, ts_utc: datetime, data: Dict[str, Any]) -> None:
        query = """
            INSERT INTO positions (
                ts_utc, node_id, lat, lon, alt, speed, heading, accuracy,
                battery_v, rssi, snr, seq_no, hop_limit, gateway_id, channel_id, msg_id, raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self._execute(
            query,
            (
                ts_utc,
                node_id,
                data.get("lat"),
                data.get("lon"),
                data.get("alt"),
                data.get("speed"),
                data.get("heading"),
                data.get("accuracy"),
                data.get("battery_v"),
                data.get("rssi"),
                data.get("snr"),
                data.get("seq_no"),
                data.get("hop_limit"),
                data.get("gateway_id"),
                data.get("channel_id"),
                data.get("msg_id"),
                Json(data.get("raw_payload")) if data.get("raw_payload") is not None else None,
            ),
        )

    def upsert_gateway(self, gateway_id: str) -> None:
        query = """
            INSERT INTO gateways (gateway_id, last_seen)
            VALUES (%s, NOW())
            ON CONFLICT (gateway_id) DO UPDATE
            SET last_seen = NOW();
        """
        self._execute(query, (gateway_id,))

    def save_raw(self, topic: str, payload: bytes) -> None:
        query = "INSERT INTO raw_packets (topic, payload) VALUES (%s, %s)"
        self._execute(query, (topic, Binary(payload)))

    def save_message(self, node_id: str, ts_utc: datetime, data: Dict[str, Any]) -> None:
        query = """
            INSERT INTO messages (
                ts_utc, node_id, to_node, channel_id, text_body, rx_time, rssi, snr,
                hop_limit, msg_id, seq_no, gateway_id, raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self._execute(
            query,
            (
                ts_utc,
                node_id,
                data.get("to_node"),
                data.get("channel_id"),
                data.get("text_body"),
                data.get("rx_time"),
                data.get("rssi"),
                data.get("snr"),
                data.get("hop_limit"),
                data.get("msg_id"),
                data.get("seq_no"),
                data.get("gateway_id"),
                Json(data.get("raw_payload")) if data.get("raw_payload") is not None else None,
            ),
        )

    def _execute(self, query: str, params: tuple) -> None:
        def run_once():
            with self._lock:
                with self._conn.cursor() as cur:
                    cur.execute(query, params)

        try:
            run_once()
        except (AttributeError, OperationalError):
            # Attempt a reconnect and retry once
            self.connect()
            run_once()

    def __del__(self):
        self.close()
