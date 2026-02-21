"""Platform for the Daikin Test AC (Madoka BRC1H via BLE)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import MadokaCoordinator

PLATFORMS = ["climate", "sensor", "binary_sensor", "button", "number"]

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry to new format."""
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
    """Set up the component (YAML not supported)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Daikin Madoka from a config entry."""
    address: str = entry.data["address"]

    coordinator = MadokaCoordinator(hass, address)

    try:
        await coordinator.async_start()
        _LOGGER.info("✅ BLE started for Madoka %s", address)
    except Exception as err:
        _LOGGER.error("❌ Failed to start BLE for %s: %s", address, err)
        raise

    # First data refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: MadokaCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok


