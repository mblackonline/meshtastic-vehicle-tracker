# Meshtastic Vehicle Tracker

Open-source vehicle fleet tracking system using Meshtastic LoRa mesh network for GPS telemetry and messaging during network outages.

## Overview

Emergency backup tracking system for fleet vehicles when internet connectivity is unavailable. Uses LoRa mesh networking to relay GPS positions and text messages from vehicles to a central collection server via MQTT.

**Key Features:**
- Real-time GPS position tracking via LoRa mesh
- Text messaging between vehicles and dispatch
- PostgreSQL database storage with time-series data
- Web dashboard for live map visualization
- Docker-based deployment for easy setup
- Supports multiple Meshtastic hardware devices

## Use Cases

- Transit agencies (buses, shuttles, paratransit)
- Emergency services backup communications
- Fleet management in rural/remote areas
- Disaster response vehicle coordination
- School bus fleets
- Delivery and logistics operations

## Architecture

**Normal Operations:**
```
Vehicle Trackers → LoRa Mesh → Repeaters → Gateways → MQTT Broker → Database → Dashboard
```

**System Components:**
- **Vehicle Trackers:** GPS-enabled Meshtastic devices (T1000-E, etc.)
- **Gateways:** Network-connected Meshtastic devices that bridge LoRa mesh to MQTT
- **MQTT Broker:** Mosquitto message broker for data collection
- **Collector:** Python service that subscribes to MQTT and writes to PostgreSQL
- **Database:** PostgreSQL for telemetry storage
- **Web Dashboard:** FastAPI + MapLibre GL for live tracking visualization

**During Internet Outage:**
- LoRa mesh continues functioning independently
- Local gateways maintain tracking at primary facility
- Remote sites use Meshtastic phone apps for coordination

## Hardware Requirements

### Gateways (Network-Connected)
- WisMesh WiFi Gateway (~$120-200)
- WisMesh Ethernet Gateway with PoE (~$200-300)
- RAK Wireless development boards (~$50-150)

### Vehicle Trackers
- SenseCAP T1000-E GPS Tracker (~$50-80)
- Heltec WiFi LoRa V3 with external GPS (~$40-60)
- RAK Wireless GPS trackers (~$50-100)

### Optional Repeaters (Range Extension)
- Any Meshtastic-compatible device
- Heltec LoRa devices (~$20-40)
- LilyGO T-Beam with GPS (~$40-60)

**Coverage Estimates:**
- Urban environment: 2-5km between nodes
- Suburban: 5-10km between nodes
- Rural/line-of-sight: 10-40km between nodes

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.8+ (for device configuration only)
- Meshtastic CLI tool: `pip install meshtastic`

### 1. Setup Environment

```bash
# Clone repository
git clone https://github.com/yourusername/meshtastic-vehicle-tracker.git
cd meshtastic-vehicle-tracker

# Create and configure environment
cp .env.example .env
nano .env  # Edit: WiFi credentials, MQTT broker IP, database credentials

# Start all services
docker compose up -d --build
```

All services start automatically:
- **Mosquitto** MQTT broker on port 1883
- **PostgreSQL** database on port 5432
- **Collector** MQTT subscriber and database writer
- **Web Dashboard** on http://localhost:8000

The collector will:
- Wait for PostgreSQL to be healthy
- Auto-create database schema on first run
- Begin collecting telemetry from MQTT broker

### 2. Configure Devices

**Important:** MQTT broker must be running before configuring devices.

#### Gateway Device (Network-Connected)

```bash
# Generate configuration from template
python device-setup/generate_config.py

# Connect gateway via USB
meshtastic --port /dev/ttyUSB0 --configure device-setup/wismesh-gateway-config.yaml
```

Gateway connects to WiFi/Ethernet and MQTT broker immediately after reboot.

#### Vehicle Tracker Devices (T1000-E)

```bash
# Edit generate_config.py to uncomment T1000e section
python device-setup/generate_config.py

# Connect each device via USB (one at a time)
meshtastic --port /dev/ttyACM0 --configure device-setup/t1000e-vehicle1-config.yaml
meshtastic --port /dev/ttyACM0 --configure device-setup/t1000e-vehicle2-config.yaml
```

**T1000-E Device Notes:**
- Transmits GPS via LoRa mesh to gateway
- No direct MQTT connection (mesh only)
- Bluetooth connection for phone app (messaging, configuration)
- Built-in rechargeable battery with solar charging option

## Configuration Details

### Gateway Settings
- Network connectivity: WiFi or Ethernet
- MQTT enabled: `true`
- JSON output: `true`
- Encryption: `false` (for open monitoring) or `true` (for private channels)
- Optional: Fixed GPS coordinates if gateway is stationary

### Tracker Settings
- MQTT enabled: `false` (uses LoRa mesh only)
- LoRa transmit: `true`
- GPS update interval: 300 seconds (5 minutes recommended)
- Position broadcast: Enabled
- Bluetooth: Enabled (for phone app)

### Meshtastic Presets

**Urban/Dense Deployments (0-20km coverage):**
```yaml
Preset: MEDIUM_FAST
position_broadcast_secs: 300  # 5 minutes
telemetry.device_update_interval: 3600  # 1 hour
hop_limit: 3
```

**Rural/Sparse Deployments (20km+ coverage):**
```yaml
Preset: LONG_MODERATE
position_broadcast_secs: 300
telemetry.device_update_interval: 3600
hop_limit: 4
```

## Monitoring and Management

```bash
# View collector logs
docker compose logs -f collector

# View all service logs
docker compose logs -f

# Restart collector
docker compose restart collector

# Stop all services
docker compose down

# Stop and remove data (DELETES DATABASE)
docker compose down -v

# Complete cleanup (removes all Docker data)
docker system prune -a --volumes -f
```

## Database Schema

Schema is automatically created on first collector run:

**Tables:**
- `devices` - Mesh nodes (auto-populated from telemetry)
- `positions` - GPS telemetry with RSSI/SNR signal metrics
- `messages` - Text messages between nodes
- `gateways` - Gateway infrastructure (manually populated)
- `raw_packets` - Unparsed packets for debugging

**Indexes:**
- `idx_positions_node_time` - Fast position lookups by vehicle and time
- `idx_messages_node_time` - Fast message lookups by vehicle and time
- `idx_raw_topic_time` - Fast raw packet lookups by topic

## Web Dashboard

Access the live tracking map at http://localhost:8000

**Features:**
- Real-time vehicle positions on interactive map
- Automatic clustering for overlapping markers
- Vehicle info popups (ID, speed, last update time)
- Auto-refresh every 10 seconds
- Mobile-responsive design

**API Endpoint:**
- `GET /api/buses` - Returns GeoJSON FeatureCollection of latest vehicle positions

## Project Structure

```
meshtastic-vehicle-tracker/
├── meshtastic_collector/     # MQTT subscriber and PostgreSQL writer
│   ├── mqtt_collector.py     # Main collector service
│   └── db.py                  # Database operations
├── web/                       # Web dashboard
│   ├── main.py                # FastAPI application
│   └── static/                # HTML, CSS, JS for map interface
├── device-setup/              # Device configuration
│   ├── generate_config.py    # Template-based config generator
│   ├── wismesh-gateway-template.yaml.template
│   └── t1000e-template.yaml.template
├── docker-compose.yml         # Service orchestration
├── Dockerfile                 # Collector container image
```

## Example Deployment

**Scenario:** Small transit agency with 10 vehicles

**Hardware:**
- 1 WisMesh WiFi Gateway at dispatch center ($150)
- 10 T1000-E GPS trackers for vehicles ($600)
- 2 Heltec repeaters for coverage extension ($80)
- **Total:** ~$830

**Coverage:**
- Urban area: 10km radius
- Position updates: Every 5 minutes
- Battery life: 24+ hours on vehicle trackers

## Advanced Configuration

### Custom Device Configurations

Edit `device-setup/generate_config.py` to customize:
- Channel URLs and encryption keys
- WiFi credentials per device
- MQTT broker addresses
- GPS update intervals
- LoRa region settings

## Troubleshooting

**Collector won't start:**
- Check PostgreSQL is healthy: `docker compose ps`
- Verify .env variables are set correctly
- Check logs: `docker compose logs collector`

**No data appearing in database:**
- Verify MQTT broker is running: `docker compose ps mosquitto`
- Check devices are publishing: `mosquitto_sub -h localhost -t 'msh/#' -v`
- Confirm device MQTT settings match .env configuration

**Devices won't connect to MQTT:**
- Verify broker IP address in device config matches server LAN IP
- Check WiFi credentials are correct
- Ensure devices have network connectivity
- Gateway devices only: Check `mqtt.enabled: true` in config

**Poor mesh coverage:**
- Add repeater nodes in areas with weak signal
- Adjust LoRa preset (try LONG_MODERATE for better range)
- Increase hop_limit (default 3, max 7)
- Check antenna connections

## Contributing

Contributions welcome! Please:
- Fork the repository
- Create a feature branch
- Submit a pull request with clear description

## License

[MIT License](LICENSE)

## Acknowledgments

- Initial MQTT implementation inspired by [MQTT Basics with Python Examples](https://medium.com/@codeanddogs/mqtt-basics-with-python-examples-7c758e605d4) by Code and Dogs
- MQTT tutorial: [Python MQTT Tutorial](https://www.youtube.com/watch?v=kuyCd53AOtg) on YouTube
- Web dashboard based on [GOCARTA MOCS Express Map](https://github.com/gocarta/mocs-express-map) (CC0 1.0 Universal)
- Built with [Meshtastic](https://meshtastic.org) open-source mesh networking platform

## Support

- GitHub Issues: Report bugs or request features
- Meshtastic Community: [Discord](https://discord.gg/ktMAKGBnBs) and [Forum](https://meshtastic.discourse.group/)
