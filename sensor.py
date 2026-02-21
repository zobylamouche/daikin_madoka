"""Sensor platform for Daikin Madoka BRC1H.

Exposes the following sensor entities:
- Indoor temperature  (°C, from the built-in room sensor)
- Outdoor temperature  (°C, from the outdoor unit, may be unavailable)
- Firmware version    (diagnostic, fetched once at startup)

All sensors are CoordinatorEntity instances bound to MadokaCoordinator,
so they update automatically on each polling cycle.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MadokaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin sensors from a config entry."""
    coordinator: MadokaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        MadokaIndoorTempSensor(coordinator, entry),
        MadokaOutdoorTempSensor(coordinator, entry),
        MadokaFirmwareSensor(coordinator),
    ]
    async_add_entities(entities)


class _MadokaTempSensor(CoordinatorEntity[MadokaCoordinator], SensorEntity):
    """Base class for temperature sensors (indoor / outdoor).

    Provides common attributes: icon, device_class, unit, device_info.
    Subclasses only need to implement native_value.
    """

    _attr_icon = "mdi:thermometer"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: MadokaCoordinator,
        entry: ConfigEntry,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_{suffix}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class MadokaIndoorTempSensor(_MadokaTempSensor):
    """Indoor temperature sensor."""

    def __init__(
        self, coordinator: MadokaCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "indoor_temp", "Indoor Temperature")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.state.indoor_temperature


class MadokaOutdoorTempSensor(_MadokaTempSensor):
    """Outdoor temperature sensor."""

    _attr_icon = "mdi:thermometer-lines"

    def __init__(
        self, coordinator: MadokaCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "outdoor_temp", "Outdoor Temperature")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.state.outdoor_temperature


# ── Diagnostic / maintenance sensors ─────────────────────────────


class _MadokaBaseSensor(CoordinatorEntity[MadokaCoordinator], SensorEntity):
    """Base class for non-temperature sensors (firmware, etc.).

    Similar to _MadokaTempSensor but without temperature-specific
    attributes (device_class, unit).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MadokaCoordinator,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_{suffix}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class MadokaFirmwareSensor(_MadokaBaseSensor):
    """Diagnostic sensor showing the remote controller firmware version.

    The version is fetched once (CMD 0x0130) and cached in MadokaState.
    Displayed as e.g. "1.2.3" in the HA entity.
    """

    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MadokaCoordinator) -> None:
        super().__init__(coordinator, "firmware_rc", "Firmware Version")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.state.firmware_rc

