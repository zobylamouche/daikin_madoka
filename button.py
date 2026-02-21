"""Button platform for Daikin Madoka — Reset clean filter indicator.

Provides a ButtonEntity that, when pressed, sends CMD 0x4220 to the
thermostat to:
  - Disable the clean-filter indicator LED
  - Reset the internal filter usage timer

This should be pressed after physically cleaning the air filter.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up Daikin Madoka buttons."""
    coordinator: MadokaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MadokaResetFilterButton(coordinator)])


class MadokaResetFilterButton(
    CoordinatorEntity[MadokaCoordinator], ButtonEntity
):
    """Button to reset the clean filter indicator and usage timer.

    After cleaning the physical filter, press this button to clear
    the warning and restart the filter timer on the thermostat.
    """

    _attr_icon = "mdi:air-filter"
    _attr_has_entity_name = True
    _attr_name = "Reset Filter"

    def __init__(self, coordinator: MadokaCoordinator) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_reset_filter"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    async def async_press(self) -> None:
        """Handle the button press — reset filter indicator."""
        _LOGGER.info("Resetting clean filter indicator for %s", self._address)
        await self.coordinator.async_reset_filter()
