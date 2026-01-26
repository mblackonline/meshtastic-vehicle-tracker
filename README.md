# Meshtastic Vehicle Tracker

GPS vehicle tracking system using Meshtastic LoRa mesh network. Works during internet outages by relaying position data through mesh nodes to a central collector.

## What It Does

- Tracks vehicle positions via LoRa mesh network
- Stores GPS telemetry in PostgreSQL database
- Displays live vehicle locations on web map
- Works when internet is down (mesh continues functioning)
- Text messaging between vehicles and dispatch

## Quick Start

### Requirements
- Docker and Docker Compose
- Meshtastic hardware (gateways + vehicle trackers)
- Python 3.8+ (for device configuration)

### Installation

1. **Clone and configure**
   ```bash
   git clone https://github.com/mblackonline/meshtastic-vehicle-tracker.git
   cd meshtastic-vehicle-tracker
   cp .env.example .env
   nano .env  # Set WiFi credentials, MQTT broker IP, database password
   ```

2. **Start services**
   ```bash
   docker compose up -d --build
   ```

3. **Access dashboard**
   
   Open http://localhost:8000

All services start automatically:
- Mosquitto MQTT broker (port 1883)
- PostgreSQL database (port 5432)
- Data collector
- Web dashboard (port 8000)

### Configure Devices

**Gateway (network-connected):**
```bash
python device-setup/generate_config.py
meshtastic --port /dev/ttyUSB0 --configure device-setup/wismesh-gateway-config.yaml
```

**Vehicle trackers (T1000-E):**
```bash
# Edit generate_config.py to uncomment tracker section
python device-setup/generate_config.py
meshtastic --port /dev/ttyACM0 --configure device-setup/t1000e-test1-config.yaml
```

See `device-setup/README.md` for detailed configuration options.

## Hardware

**Gateways** (WiFi/Ethernet connected):
- WisMesh WiFi Gateway
- WisMesh Ethernet Gateway with PoE
- RAK Wireless boards

**Vehicle Trackers** (GPS + LoRa):
- SenseCAP T1000-E
- Heltec WiFi LoRa V3 with GPS
- RAK Wireless GPS trackers

**Optional Repeaters** (extend range):
- Any Meshtastic-compatible device

## Architecture

```
Vehicle Trackers (GPS) 
    ↓ LoRa mesh
Gateways (WiFi/Ethernet)
    ↓ MQTT
Collector → PostgreSQL
    ↓
Web Dashboard
```

## Monitoring

```bash
# View logs
docker compose logs -f

# Check services
docker compose ps

# Restart collector
docker compose restart collector

# Stop everything
docker compose down

# Complete reset (deletes data)
docker compose down -v
```

## Database Schema

Auto-created tables:
- `devices` - Mesh nodes
- `positions` - GPS telemetry with signal strength
- `messages` - Text messages
- `gateways` - Gateway infrastructure
- `raw_packets` - Debug data

## API

`GET /api/buses` - Returns GeoJSON of latest vehicle positions

## License

[MIT License](LICENSE)

## Credits

- MQTT implementation: [MQTT Basics with Python](https://medium.com/@codeanddogs/mqtt-basics-with-python-examples-7c758e605d4)
- Web dashboard: [GOCARTA MOCS Express Map](https://github.com/gocarta/mocs-express-map) (CC0)
- Built with [Meshtastic](https://meshtastic.org)

