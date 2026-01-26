import json
import os
import signal
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from .db import Database

try:
    from meshtastic.protobuf import mqtt_pb2, mesh_pb2
    HAS_PROTO = True
except ImportError:
    HAS_PROTO = False

# Fallback numeric portnums in case enums are missing in this protobuf build
TEXT_PORTNUM = 1  # TEXT_MESSAGE_APP
POSITION_PORTNUM = 4  # POSITION_APP


load_dotenv()  # Load settings from .env if present

STOP = threading.Event()

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_ROOT = os.environ.get("MESHTASTIC_MQTT_ROOT", "msh/fleet")
# Subscribe to JSON and protobuf branches (with optional region segment)
MQTT_TOPICS = [
    f"{MQTT_ROOT}/json/#",
    f"{MQTT_ROOT}/+/json/#",
    f"{MQTT_ROOT}/e/#",
    f"{MQTT_ROOT}/+/e/#",
]


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        return None


def _node_id_from_int(num: Optional[int]) -> Optional[str]:
    if num is None:
        return None
    try:
        return f"!{num:08x}"
    except Exception:
        return None


def _normalize_node_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, int):
        return _node_id_from_int(value)
    if isinstance(value, str):
        if value.startswith("!"):
            return value
        if value.isdigit():
            try:
                return _node_id_from_int(int(value))
            except Exception:
                return value
        return value
    return value


def _proto_has_fields(message: Any) -> bool:
    return bool(getattr(message, "ListFields", None) and message.ListFields())


def _hw_model_to_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if HAS_PROTO:
        model_enum = getattr(mesh_pb2, "HardwareModel", None)
        if model_enum is not None:
            try:
                return model_enum.Name(int(value))
            except Exception:
                pass
    return str(value)


def _user_from_proto(user: Any) -> Dict[str, Any]:
    return {
        "id": getattr(user, "id", None),
        "longName": getattr(user, "long_name", None) or getattr(user, "longName", None),
        "shortName": getattr(user, "short_name", None) or getattr(user, "shortName", None),
        "hwModel": _hw_model_to_string(
            getattr(user, "hw_model", None) or getattr(user, "hwModel", None)
        ),
    }


def _decode_user_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if not HAS_PROTO:
        return None
    user_cls = getattr(mesh_pb2, "User", None)
    if user_cls is None or not payload:
        return None
    try:
        user = user_cls()
        user.ParseFromString(bytes(payload))
    except Exception:
        return None
    if not _proto_has_fields(user):
        return None
    return _user_from_proto(user)


def _extract_user_dict(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    decoded = payload.get("decoded") if isinstance(payload.get("decoded"), dict) else {}
    candidates = [
        decoded.get("user"),
        decoded.get("nodeInfo"),
        decoded.get("nodeinfo"),
        payload.get("user"),
        payload.get("nodeInfo"),
        payload.get("nodeinfo"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return None


def _normalize_user_dict(user: Dict[str, Any]) -> Dict[str, Optional[str]]:
    long_name = user.get("longName") or user.get("long_name")
    short_name = user.get("shortName") or user.get("short_name")
    hw_model = user.get("hwModel") or user.get("hw_model")
    if hw_model is not None and not isinstance(hw_model, str):
        hw_model = str(hw_model)
    return {
        "display_name": long_name or short_name,
        "hw_model": hw_model,
    }


def _ingest_device_info(db: Database, payload: Dict[str, Any]) -> None:
    user = _extract_user_dict(payload)
    if not user:
        return

    node_id = (
        _normalize_node_id(user.get("id"))
        or _normalize_node_id(user.get("node_id"))
        or _normalize_node_id(user.get("nodeId"))
        or _normalize_node_id(payload.get("from"))
    )
    if not node_id:
        return

    info = _normalize_user_dict(user)
    if info["display_name"] is None and info["hw_model"] is None:
        return

    db.upsert_device(
        node_id=node_id,
        display_name=info["display_name"],
        hw_model=info["hw_model"],
    )


def _position_dict(pos: Any) -> Dict[str, Any]:
    lat_i = getattr(pos, "latitude_i", None)
    lon_i = getattr(pos, "longitude_i", None)
    return {
        "latitude": lat_i / 1e7 if lat_i is not None else None,
        "longitude": lon_i / 1e7 if lon_i is not None else None,
        "altitude": pos.altitude if pos.HasField("altitude") else None,
        "groundSpeed": pos.ground_speed if pos.HasField("ground_speed") else None,
        "heading": pos.heading if pos.HasField("heading") else None,
        "hAccuracy": pos.hdop if pos.HasField("hdop") else None,
    }


def _decode_position_bytes(payload: Any) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    try:
        pos = mesh_pb2.Position()
        pos.ParseFromString(bytes(payload))
        return _position_dict(pos)
    except Exception:
        return None


def _proto_to_payload(packet: Any, env: Any, topic: str = "") -> Dict[str, Any]:
    """Map ServiceEnvelope/MeshPacket to a normalized dict. Never raises."""
    decoded: Dict[str, Any] = {}
    pd = getattr(packet, "decoded", None)

    pnum = getattr(pd, "portnum", None) if pd else None
    if pnum is not None:
        decoded["portnum"] = int(pnum)

    user = getattr(pd, "user", None) if pd else None
    if user and _proto_has_fields(user):
        decoded["user"] = _user_from_proto(user)
    else:
        nodeinfo_const = getattr(mesh_pb2, "PortNum", None)
        nodeinfo_const = getattr(nodeinfo_const, "NODEINFO_APP", None)
        if pnum is not None and nodeinfo_const is not None and pnum == nodeinfo_const:
            decoded_user = None
            if pd and getattr(pd, "payload", None):
                decoded_user = _decode_user_payload(pd.payload)
            if not decoded_user and getattr(packet, "payload", None):
                decoded_user = _decode_user_payload(packet.payload)
            if decoded_user:
                decoded["user"] = decoded_user

    text_const = getattr(mesh_pb2, "PortNum", None)
    text_const = getattr(text_const, "TEXT_MESSAGE_APP", TEXT_PORTNUM)

    if pnum == text_const:
        text_body = None
        txt = getattr(pd, "text", None)
        if txt and getattr(txt, "msg", None):
            text_body = txt.msg
        elif pd and getattr(pd, "payload", None):
            text_body = pd.payload.decode(errors="ignore")
        if text_body:
            decoded["text"] = text_body

    pos_const = getattr(mesh_pb2, "PortNum", None)
    pos_const = getattr(pos_const, "POSITION_APP", POSITION_PORTNUM)

    if pnum == pos_const:
        pos_dict = None
        if pd and getattr(pd, "position", None):
            pos = pd.position
            if getattr(pos, "ListFields", None) and pos.ListFields():
                pos_dict = _position_dict(pos)
        if not pos_dict and pd and getattr(pd, "payload", None):
            pos_dict = _decode_position_bytes(pd.payload)
        if not pos_dict and getattr(packet, "payload", None):
            pos_dict = _decode_position_bytes(packet.payload)
        if pos_dict:
            decoded["position"] = pos_dict
        else:
            payload_len = len(getattr(pd, "payload", b"") or b"") if pd else 0
            print(f"POSITION_APP decode failed (payload_len={payload_len}) topic={topic}")

    src = (
        _node_id_from_int(getattr(env, "from_", None))
        or _node_id_from_int(getattr(env, "from", None))
        or _node_id_from_int(getattr(packet, "from_", None))
        or _node_id_from_int(getattr(packet, "from", None))
        or "unknown"
    )
    dst = (
        _node_id_from_int(getattr(env, "to", None))
        or _node_id_from_int(getattr(env, "to_", None))
        or _node_id_from_int(getattr(packet, "to", None))
        or _node_id_from_int(getattr(packet, "to_", None))
    )

    return {
        "from": src,
        "to": dst,
        "channel": getattr(env, "channel_id", None)
        or getattr(env, "channel", None)
        or getattr(packet, "channel", None),
        "id": getattr(packet, "id", None),
        "rxTime": getattr(env, "rx_time", None),
        "rssi": getattr(env, "rx_rssi", None) or getattr(env, "rssi", None),
        "snr": getattr(env, "rx_snr", None) or getattr(env, "snr", None),
        "hopLimit": getattr(packet, "hop_limit", None),
        "viaMqtt": getattr(env, "gateway_id", None),
        "topic": topic,
        "decoded": decoded,
    }


def _envelope_to_payload(env: Any, topic: str = "") -> Dict[str, Any]:
    """Handle ServiceEnvelope that contains decoded but no MeshPacket."""
    decoded: Dict[str, Any] = {}
    pnum = getattr(env.decoded, "portnum", None) if env and env.decoded else None
    if pnum is not None:
        decoded["portnum"] = int(pnum)

    user = getattr(env.decoded, "user", None) if env and env.decoded else None
    if user and _proto_has_fields(user):
        decoded["user"] = _user_from_proto(user)
    else:
        nodeinfo_const = getattr(mesh_pb2, "PortNum", None)
        nodeinfo_const = getattr(nodeinfo_const, "NODEINFO_APP", None)
        if pnum is not None and nodeinfo_const is not None and pnum == nodeinfo_const:
            decoded_user = None
            if env and env.decoded and getattr(env.decoded, "payload", None):
                decoded_user = _decode_user_payload(env.decoded.payload)
            if decoded_user:
                decoded["user"] = decoded_user

    text_const = getattr(mesh_pb2, "PortNum", None)
    text_const = getattr(text_const, "TEXT_MESSAGE_APP", TEXT_PORTNUM)

    if pnum == text_const:
        text_body = None
        if env.decoded.text and env.decoded.text.msg:
            text_body = env.decoded.text.msg
        elif env.decoded.payload:
            text_body = env.decoded.payload.decode(errors="ignore")
        if text_body:
            decoded["text"] = text_body

    pos_const = getattr(mesh_pb2, "PortNum", None)
    pos_const = getattr(pos_const, "POSITION_APP", POSITION_PORTNUM)

    if pnum == pos_const:
        pos_dict = None
        if env.decoded.HasField("position"):
            pos_dict = _position_dict(env.decoded.position)
        if not pos_dict and env.decoded.payload:
            pos_dict = _decode_position_bytes(env.decoded.payload)
        if pos_dict:
            decoded["position"] = pos_dict

    src = (
        _node_id_from_int(getattr(env, "from_", None))
        or _node_id_from_int(getattr(env, "from", None))
        or "unknown"
    )
    dst = _node_id_from_int(getattr(env, "to", None)) or _node_id_from_int(
        getattr(env, "to_", None)
    )

    return {
        "from": src,
        "to": dst,
        "channel": getattr(env, "channel", None),
        "id": getattr(env, "id", None),
        "rxTime": getattr(env, "rx_time", None),
        "rssi": getattr(env, "rx_rssi", None) or getattr(env, "rssi", None),
        "snr": getattr(env, "rx_snr", None) or getattr(env, "snr", None),
        "hopLimit": getattr(env, "hop_limit", None),
        "viaMqtt": getattr(env, "gateway_id", None),
        "topic": topic,
        "decoded": decoded,
    }


def _extract_common(payload: Dict[str, Any]) -> Dict[str, Any]:
    decoded = payload.get("decoded", {}) or {}
    return {
        "from": _normalize_node_id(payload.get("from")),
        "to": _normalize_node_id(payload.get("to")),
        "channel_id": payload.get("channel"),
        "msg_id": payload.get("id"),
        "seq_no": decoded.get("id") if isinstance(decoded.get("id"), int) else payload.get("id"),
        "rx_time": _parse_ts(payload.get("rxTime")),
        "rssi": payload.get("rssi"),
        "snr": payload.get("snr"),
        "hop_limit": payload.get("hopLimit"),
        "gateway_id": _normalize_node_id(payload.get("viaMqtt")),
        "portnum": decoded.get("portnum"),
        "decoded": decoded,
    }


def _looks_like_position(pos: Any) -> bool:
    if not isinstance(pos, dict):
        return False
    keys = {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "latitude_i",
        "longitude_i",
    }
    return any(k in pos for k in keys)


def _extract_position_payload(packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    decoded = packet.get("decoded", {}) if isinstance(packet.get("decoded"), dict) else {}
    candidates = [
        decoded.get("position"),
        decoded.get("payload"),
        packet.get("position"),
        packet.get("payload"),
    ]
    for candidate in candidates:
        if _looks_like_position(candidate):
            return candidate
    return None


def _normalize_position(position: Dict[str, Any]) -> Dict[str, Any]:
    lat = position.get("latitude")
    lon = position.get("longitude")
    if lat is None and "latitude_i" in position:
        lat = position.get("latitude_i") / 1e7
    if lon is None and "longitude_i" in position:
        lon = position.get("longitude_i") / 1e7
    return {
        "latitude": lat if lat is not None else position.get("lat"),
        "longitude": lon if lon is not None else position.get("lon"),
        "altitude": position.get("altitude") or position.get("alt"),
        "groundSpeed": position.get("groundSpeed") or position.get("ground_speed"),
        "heading": position.get("heading"),
        "hAccuracy": position.get("hAccuracy") or position.get("hdop"),
        "pdop": position.get("pdop"),
    }


def handle_position(db: Database, packet: Dict[str, Any]) -> None:
    common = _extract_common(packet)
    raw_position = _extract_position_payload(packet)
    if not raw_position:
        return
    position = _normalize_position(raw_position)

    node_id = common.get("from")
    ts = common.get("rx_time") or datetime.now(timezone.utc)

    db.upsert_device(node_id=node_id, display_name=None, hw_model=None)
    db.save_position(
        node_id=node_id,
        ts_utc=ts,
        data={
            "lat": position.get("latitude") or position.get("lat"),
            "lon": position.get("longitude") or position.get("lon"),
            "alt": position.get("altitude") or position.get("alt"),
            "speed": position.get("groundSpeed"),
            "heading": position.get("heading"),
            "accuracy": position.get("pdop") or position.get("hAccuracy"),
            "battery_v": (packet.get("deviceMetrics") or {}).get("voltage"),
            "rssi": common.get("rssi"),
            "snr": common.get("snr"),
            "seq_no": common.get("seq_no"),
            "hop_limit": common.get("hop_limit"),
            "gateway_id": common.get("gateway_id"),
            "channel_id": common.get("channel_id"),
            "msg_id": common.get("msg_id"),
            "raw_payload": packet,
        },
    )


def handle_text(db: Database, packet: Dict[str, Any]) -> None:
    common = _extract_common(packet)
    decoded = common.get("decoded", {})
    text_body = decoded.get("text") or decoded.get("payload")
    if not text_body:
        return

    node_id = common.get("from")
    ts = common.get("rx_time") or datetime.now(timezone.utc)

    db.upsert_device(node_id=node_id, display_name=None, hw_model=None)
    db.save_message(
        node_id=node_id,
        ts_utc=ts,
        data={
            "to_node": common.get("to"),
            "channel_id": common.get("channel_id"),
            "text_body": text_body,
            "rx_time": common.get("rx_time"),
            "rssi": common.get("rssi"),
            "snr": common.get("snr"),
            "hop_limit": common.get("hop_limit"),
            "msg_id": common.get("msg_id"),
            "seq_no": common.get("seq_no"),
            "gateway_id": common.get("gateway_id"),
            "raw_payload": packet,
        },
    )


def _route_payload(db: Database, payload: Dict[str, Any]) -> None:
    _ingest_device_info(db, payload)
    decoded = payload.get("decoded", {}) or {}
    portnum = decoded.get("portnum")
    src = payload.get("from")

    if decoded.get("text") or portnum == 1:
        handle_text(db, payload)
        print(f"decoded text from {payload.get('from')}")
    elif decoded.get("position") or _looks_like_position(decoded.get("payload")):
        handle_position(db, payload)
        print(f"decoded position from {payload.get('from')}")
    else:
        if _looks_like_position(payload.get("position")) or _looks_like_position(payload.get("payload")):
            handle_position(db, payload)
        else:
            try:
                db.save_raw(payload.get("topic", ""), json.dumps(payload).encode())
            except Exception:
                pass


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to MQTT {MQTT_HOST}:{MQTT_PORT}, subscribing to {MQTT_TOPICS}")
        for topic in MQTT_TOPICS:
            result, mid = client.subscribe(topic, qos=1)
            if result == mqtt.MQTT_ERR_SUCCESS:
                print(f"Subscribed to {topic}")
            else:
                print(f"Failed to subscribe to {topic}: {result}")
    else:
        print(f"MQTT connect failed: {reason_code}")


def on_message(client, userdata, message):
    db: Database = userdata["db"]
    topic = message.topic or ""

    # If this isn't a JSON topic, keep the raw bytes and return
    if "/json/" not in topic:
        # Attempt protobuf decode if available
        if HAS_PROTO:
            try:
                env = mqtt_pb2.ServiceEnvelope()
                env.ParseFromString(message.payload)
                env_fields = env.ListFields()
                print(f"recv {topic} env fields: {[(f.name, v) for f, v in env_fields]}")

                pkt = None
                if env.packet:
                    pkt = env.packet
                elif env.data:
                    pkt = mesh_pb2.MeshPacket()
                    pkt.ParseFromString(env.data)

                if pkt:
                    mapped = _proto_to_payload(pkt, env, topic)
                    _route_payload(db, mapped)
                    return

                # No packet? try envelope decoded if present
                mapped = _envelope_to_payload(env, topic)
                if mapped:
                    _route_payload(db, mapped)
                    print("decoded envelope-only packet")
                    return
            except Exception as e:
                print(f"protobuf decode error on {topic}: {e}")

        # Fallback: store raw
        try:
            db.save_raw(topic, message.payload)
        except Exception as e:
            print(f"Failed to store raw packet from {topic}: {e}")
        return

    # JSON path: decode and parse; on failure, keep raw
    try:
        payload_text = message.payload.decode(errors="replace")
        payload = json.loads(payload_text)
    except Exception:
        try:
            db.save_raw(topic, message.payload)
        except Exception as e:
            print(f"Failed to store raw packet from {topic}: {e}")
        return

    _route_payload(db, payload)


def on_disconnect(client, userdata, flags, reason_code, properties):
    print("MQTT disconnected")


def ask_exit(*args):
    print("Stopping Meshtastic MQTT collector...")
    STOP.set()


def main():
    db = Database()
    db.connect()
    db.ensure_schema()
    print(f"PostgreSQL connected at {db.host}:{db.port}, DB: {db.database}")
    print(f"Protobuf decode enabled: {HAS_PROTO}")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="Meshtastic_MQTT_Collector",
        protocol=mqtt.MQTTv5,
        userdata={"db": db},
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    print("Collector running. Press Ctrl+C to stop.")
    try:
        STOP.wait()
    finally:
        client.loop_stop()
        client.disconnect()
        db.close()
        print("Collector stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, ask_exit)
    signal.signal(signal.SIGTERM, ask_exit)
    main()
