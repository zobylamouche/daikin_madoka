"""Number platform for Daikin Madoka — Eye LED brightness.

Exposes a slider (0–19) to control the brightness of the status LED
on the front of the BRC1H thermostat.  0 = LED off, 19 = maximum.
The value is read via CMD 0x0302 and set via CMD 0x4302.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up Daikin Madoka number entities."""
    coordinator: MadokaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MadokaEyeBrightness(coordinator)])


class MadokaEyeBrightness(
    CoordinatorEntity[MadokaCoordinator], NumberEntity
):
    """Number entity to control the eye LED brightness (0–19).

    The BRC1H has a small status LED ("eye") on its front panel.
    This entity lets the user dim or turn off that LED.
    Presented as a slider in the HA frontend.
    """

    _attr_icon = "mdi:brightness-6"
    _attr_has_entity_name = True
    _attr_name = "Eye Brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 19
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: MadokaCoordinator) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_eye_brightness"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    @property
    def native_value(self) -> float | None:
        """Return the current brightness level."""
        val = self.coordinator.state.eye_brightness
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the eye brightness level."""
        level = int(value)
        _LOGGER.info("Setting eye brightness to %d for %s", level, self._address)
        await self.coordinator.async_set_eye_brightness(level)
