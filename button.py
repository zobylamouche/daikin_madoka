"""Button platform for Daikin Madoka — Reset clean filter indicator."""
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
    """Button to reset the clean filter indicator and timer."""

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
