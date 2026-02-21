# Daikin Madoka BRC1H — Home Assistant Integration

Custom integration for controlling **Daikin Madoka BRC1H** thermostats via Bluetooth Low Energy (BLE) in [Home Assistant](https://www.home-assistant.io/).

![Madoka thermostat](images/madoka.png)

## Features

| Entity | Type | Description |
|--------|------|-------------|
| Climate | `climate` | Full HVAC control — heat, cool, auto, dry, fan-only, off |
| Indoor Temperature | `sensor` | Current room temperature (°C) |
| Outdoor Temperature | `sensor` | Outdoor unit temperature (°C, when available) |
| Clean Filter | `binary_sensor` | Indicates when the air filter needs cleaning |
| Reset Filter | `button` | Clears the filter warning and resets the timer |
| Eye Brightness | `number` | Controls the front LED brightness (0–19) |
| Firmware Version | `sensor` | Remote controller firmware (diagnostic) |

![Integration](images/integration.png) ![Climate](images/climate.png) ![Entities](images/entities.png)

## Architecture

This integration communicates directly with the BRC1H over BLE using a **clean-room TLV protocol implementation** — no dependency on `pymadoka`.

| Module | Role |
|--------|------|
| `madoka_protocol.py` | BLE GATT TLV protocol: command builders, chunk assembly, response decoders |
| `bluetooth.py` | BLE connection management with auto-reconnect and backoff |
| `coordinator.py` | HA `DataUpdateCoordinator` — polls the device and exposes `MadokaState` |
| `climate.py` | `ClimateEntity` with HVAC modes, fan speeds, setpoints |
| `sensor.py` | Temperature sensors + firmware version diagnostic |
| `binary_sensor.py` | Clean filter indicator |
| `button.py` | Reset filter button |
| `number.py` | Eye LED brightness slider |
| `config_flow.py` | Manual MAC entry + Bluetooth auto-discovery |

## Requirements

- **Home Assistant** 2024.1 or later
- **Bluetooth adapter** accessible to HA (built-in or USB dongle)
- The thermostat must be **paired** with the host system before adding the integration

### Pairing the thermostat

1. On the thermostat, go to the Bluetooth menu and **forget** any existing connections.
2. On the HA host, open a terminal and run:
   ```bash
   bluetoothctl
   agent KeyboardDisplay
   remove <MAC_ADDRESS>    # Remove any stale pairing
   scan on                 # Wait until the MAC appears
   scan off
   pair <MAC_ADDRESS>      # Accept the pairing prompt on the thermostat
   ```
3. The device is now ready for the integration.

> **Tip:** A dedicated Bluetooth adapter is recommended. If running HA in a VM, pass the USB adapter through to the guest.

## Installation

### Manual

1. Download or clone this repository:
   ```bash
   cd /config/custom_components
   git clone -b refactor-ble https://github.com/zobylamouche/daikin_madoka.git daikin_madoka
   ```
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Daikin Madoka**.
4. Enter the Bluetooth MAC address of your BRC1H (e.g. `AA:BB:CC:DD:EE:FF`).

### Updating

```bash
cd /config/custom_components/daikin_madoka
git pull
```
Then restart Home Assistant.

## Bluetooth auto-discovery

The integration automatically detects BLE devices with names matching:
- `UE878*` (common BRC1H radio module name)
- `Madoka*`
- `BRC*`
- `Daikin*`

When a matching device is found, HA will prompt you to confirm adding it.

## Troubleshooting

### "BLE device not found"

- Ensure the thermostat is paired (`bluetoothctl info <MAC>` should show `Paired: yes`).
- Check that the Bluetooth adapter is visible to HA (`bluetoothctl list`).
- If running in Docker, mount the D-Bus socket:
  ```yaml
  volumes:
    - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket
  privileged: true
  ```

### Intermittent disconnections

BLE connections to the BRC1H can be unstable. The integration automatically reconnects with exponential backoff (1s → 2s → 5s → 10s → 15s). If disconnections persist:
- Move the Bluetooth adapter closer to the thermostat.
- Reduce interference from other 2.4 GHz devices.
- Use a dedicated USB Bluetooth 5.0+ adapter.

## Changelog

### v2.0.0 (2025–2026)
- **Complete rewrite** — native HA BLE stack, no `pymadoka` dependency
- Clean-room TLV protocol implementation in `madoka_protocol.py`
- Auto-reconnect with exponential backoff
- Bluetooth auto-discovery support
- Config migration from v1.x format
- New entities: clean filter indicator, reset filter button, eye brightness slider, firmware version
- Translations: EN, ES, FR, IT, DE

### v1.1 (original)
- Discovery improvements
- Minor fixes

### v1.0 (original)
- Initial release by Manuel Durán (pymadoka-based)

## Credits

- **Manuel Durán** ([@mduran80](https://github.com/mduran80)) — original integration and pymadoka library
- **zobylamouche** ([@zobylamouche](https://github.com/zobylamouche)) — v2.0.0 rewrite with native HA BLE stack

## License

MIT — see [LICENSE](LICENSE) for details.
