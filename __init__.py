"""Daikin Madoka BRC1H integration for Home Assistant.

This integration communicates with Daikin Madoka BRC1H thermostats over
Bluetooth Low Energy (BLE) using Home Assistant's native Bluetooth stack.

It supports:
- Climate control (heat/cool/auto/dry/fan, set-point, fan speed)
- Temperature sensors (indoor and outdoor)
- Binary sensor (clean filter indicator)
- Button (reset filter indicator)
- Number entity (eye LED brightness control)
- Firmware version diagnostic sensor

No dependency on pymadoka: the BLE protocol is implemented directly
in madoka_protocol.py using the reverse-engineered GATT TLV format.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import MadokaCoordinator

# All HA entity platforms provided by this integration.
# Each platform has its own .py file in this package.
PLATFORMS = ["climate", "sensor", "binary_sensor", "button", "number"]

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries from v1.x (pymadoka-based) format.

    v1.x stored: {"devices": ["AA:BB:..."], "device": "hci0"}
    v2.x stores: {"address": "AA:BB:CC:DD:EE:FF"}

    This allows users upgrading from the original mduran80/daikin_madoka
    integration to keep their config entries without re-adding the device.
    """
    if entry.version == 1 and "address" not in entry.data:
        _LOGGER.info("Migrating config entry %s from v1 (old format)", entry.entry_id)
        old_data = dict(entry.data)
        # Old format: {"devices": ["AA:BB:..."], "device": "hci0"}
        devices = old_data.get("devices", [])
        if isinstance(devices, list) and devices:
            address = devices[0].upper()
        elif isinstance(devices, str):
            address = devices.upper()
        else:
            _LOGGER.error("Cannot migrate: no MAC address found in old config")
            return False

        hass.config_entries.async_update_entry(
            entry, data={"address": address}, version=1
        )
        _LOGGER.info("✅ Migrated config entry to new format: address=%s", address)
    return True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the component (YAML configuration is not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Daikin Madoka from a config entry.

    Creates a MadokaCoordinator which manages the BLE connection,
    performs the initial data fetch, and then forwards setup to
    all entity platforms (climate, sensor, binary_sensor, etc.).
    """
    address: str = entry.data["address"]

    coordinator = MadokaCoordinator(hass, address)

    # Start the BLE client (connects to GATT, subscribes to notifications)
    try:
        await coordinator.async_start()
        _LOGGER.info("✅ BLE started for Madoka %s", address)
    except Exception as err:
        _LOGGER.error("❌ Failed to start BLE for %s: %s", address, err)
        raise

    # Perform the first poll to populate state before entities are created
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator so entity platforms can retrieve it
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to all entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry: tear down platforms and stop BLE client."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: MadokaCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()  # Disconnect BLE gracefully
    return unload_ok


