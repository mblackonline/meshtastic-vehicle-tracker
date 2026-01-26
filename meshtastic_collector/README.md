# Meshtastic MQTT → Postgres Collector

Subscribes to Meshtastic MQTT JSON topics and writes telemetry/text into Postgres.

## Env vars
- `POSTGRES_HOST` (default `localhost`)
- `POSTGRES_PORT` (default `5432`)
- `POSTGRES_DB` (required)
- `POSTGRES_USER` (required)
- `POSTGRES_PASSWORD` (required)
- `MQTT_HOST` (default `localhost`)
- `MQTT_PORT` (default `1883`)
- `MESHTASTIC_MQTT_ROOT` (default `msh/fleet`; collector listens to `<root>/json/#`, `<root>/+/json/#`, and also `<root>/e/#`/`<root>/+/e/#` to store raw packets if JSON isn't emitted)

Dependencies: `pip install -r requirements.txt` (includes `meshtastic` so protobuf `/e/` packets can be decoded into messages/positions when JSON is absent).

## Run
```bash
export POSTGRES_DB=fleet_tracker
export POSTGRES_USER=fleet_user
export POSTGRES_PASSWORD=changeme
export MQTT_HOST=127.0.0.1
export MESHTASTIC_MQTT_ROOT=msh/fleet
python -m meshtastic_collector.mqtt_collector
```

The collector subscribes to `<root>/json/#` (and `<root>/+/json/#`) and stores:
- `positions`: decoded position payloads with metadata (RSSI/SNR/seq/hop/channel/gateway)
- `messages`: decoded text messages (portnum 1 or decoded.text)

If JSON is not emitted by your gateway and only protobuf topics appear (e.g., `<root>/2/e/...`), the collector also subscribes to the `/e/` branch. With the `meshtastic` Python package installed, it will attempt to decode protobuf packets into `messages`/`positions`; otherwise it stores raw packets in `raw_packets` for later decoding.

## Notes
- Assumes radios publish JSON (`jsonEnabled: true` in the device MQTT module config).
- Use the templates in `../device-setup` to configure fleet nodes with a shared root and broker address.
