#!/usr/bin/env python3
import os

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import register_default_jsonb
from meshtastic.protobuf import mqtt_pb2, mesh_pb2

# Load .env if present so local runs pick up the same settings as docker compose.
load_dotenv()
register_default_jsonb()

conn = psycopg2.connect(
    dbname=os.environ.get("POSTGRES_DB", "fleet_tracker"),
    user=os.environ.get("POSTGRES_USER", "fleet_user"),
    password=os.environ.get("POSTGRES_PASSWORD", "changeme"),
    host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
)
cur = conn.cursor()
cur.execute("select topic, payload from raw_packets order by id desc limit 1;")
row = cur.fetchone()
if not row:
    print("No rows found in raw_packets (nothing captured yet).")
    raise SystemExit(0)
topic, payload = row
print(f"topic: {topic}  len: {len(payload)}")

env = mqtt_pb2.ServiceEnvelope()
try:
    env.ParseFromString(payload)
    print("env fields:", env.ListFields())
    if env.data:
        pkt = mesh_pb2.MeshPacket()
        pkt.ParseFromString(env.data)
        print("mesh from env.data:", pkt.ListFields())
    if env.packet:
        print("env.packet fields:", env.packet.ListFields())
except Exception as e:
    print("envelope parse error:", e)

# try parsing payload directly as MeshPacket
try:
    pkt = mesh_pb2.MeshPacket()
    pkt.ParseFromString(payload)
    print("direct MeshPacket fields:", pkt.ListFields())
except Exception as e:
    print("direct MeshPacket parse error:", e)
