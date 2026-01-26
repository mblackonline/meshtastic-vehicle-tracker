# Device Configuration

This directory contains templates and tools for generating Meshtastic device configurations.

## Setup

1. **Copy and edit `.env` in project root:**
   ```bash
   cd ..
   cp .env.example .env
   nano .env  # Add your WiFi credentials, MQTT broker IP, etc.
   ```

2. **Generate device configs:**
   ```bash
   python device-setup/generate_config.py
   ```
   
   This creates device configs with secrets substituted from `.env`

3. **Apply to device:**
   ```bash
   # Via USB
   meshtastic --port /dev/ttyUSB0 --configure device-setup/wismesh-gateway-config.yaml
   
   # Via Bluetooth (if already paired)
   meshtastic --ble-addr <device_mac> --configure device-setup/t1000e-vehicle-01-config.yaml
   ```

## Device Types

### WisMesh WiFi Gateway
- WiFi-connected MQTT gateway
- No GPS (use fixed position or manual database entry)
- Requires: `jsonEnabled: true`, `encryptionEnabled: false`
- Template: `wismesh-gateway-template.yaml.template`

### T1000e
- Battery-powered GPS tracker
- Transmits via LoRa mesh to WisMesh Gateway
- Phone app (Bluetooth) used only for sending messages and configuration
- MQTT disabled on device (gateway handles MQTT publishing)
- Template: `t1000e-template.yaml.template`

## Files

- `*.yaml.template` - Templates with `${VARIABLE}` placeholders
- `*-config.yaml` - Generated configs (gitignored, contain secrets)
- `generate_config.py` - Script to substitute .env vars into templates

## Generating Fleet Configs

By default, `generate_config.py` creates:
- 1 gateway config: `wismesh-gateway-config.yaml`
- 2 test tracker configs: `t1000e-test1-config.yaml`, `t1000e-test2-config.yaml`

To generate configs for a full fleet, edit `generate_config.py` and uncomment/modify the loop:

```python
# Generate configs for multiple vehicles
for vehicle_num in range(1, 11):  # Vehicles 1-10
    generate_config(
        "t1000e-template.yaml.template",
        f"t1000e-vehicle-{vehicle_num:02d}-config.yaml",
        DEVICE_OWNER=f"Vehicle {vehicle_num}",
        DEVICE_SHORT=f"V{vehicle_num:02d}"
    )
```

Then apply in batch:
```bash
for config in device-setup/t1000e-vehicle-*-config.yaml; do
    echo "Unplug current device, plug next device, enter boot/USB mode, then press Enter to flash $config"
    read
    meshtastic --port /dev/ttyACM0 --configure "$config"
done
# If your OS enumerates as /dev/ttyUSB0, change the port accordingly.
```

## Security

- Generated `*-config.yaml` files are gitignored
- Never commit `.env` 
- Templates (`.yaml.template`) are safe to commit
