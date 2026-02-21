"""Binary sensor platform for Daikin Madoka — Clean filter indicator."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up Daikin Madoka binary sensors."""
    coordinator: MadokaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MadokaCleanFilterSensor(coordinator)])


class MadokaCleanFilterSensor(
    CoordinatorEntity[MadokaCoordinator], BinarySensorEntity
):
    """Binary sensor: True when filter needs cleaning."""

    _attr_icon = "mdi:air-filter"
    _attr_has_entity_name = True
    _attr_name = "Clean Filter"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: MadokaCoordinator) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_clean_filter"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.state.clean_filter_needed
