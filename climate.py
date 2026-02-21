"""Climate platform for Daikin Madoka BRC1H thermostat.

Exposes the thermostat as a ClimateEntity with:
- HVAC modes: OFF, AUTO, COOL, HEAT, DRY, FAN_ONLY
- Fan modes: AUTO, LOW, MEDIUM, HIGH
- Target temperature with 1°C step (16-32°C range)
- Current indoor temperature reading

The Madoka hardware maintains separate setpoints for cooling and heating.
In HEAT mode the heating setpoint is used; in all other modes the cooling
setpoint is displayed.  When changing temperature, both setpoints are
updated simultaneously to keep them in sync.

Important: the device ignores mode-change commands while powered off.
Therefore async_set_hvac_mode() powers ON first, waits 1 second for the
device to be ready, then sends the mode command.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MIN_TEMP, MAX_TEMP
from .coordinator import MadokaCoordinator
from .madoka_protocol import FanSpeed, MadokaState, OperationMode

_LOGGER = logging.getLogger(__name__)

# ─── Mode mappings ────────────────────────────────────────────
# Bidirectional mapping between HA HVAC modes and Madoka OperationMode enum.
HA_MODE_TO_DAIKIN = {
    HVACMode.FAN_ONLY: OperationMode.FAN,
    HVACMode.DRY: OperationMode.DRY,
    HVACMode.COOL: OperationMode.COOL,
    HVACMode.HEAT: OperationMode.HEAT,
    HVACMode.AUTO: OperationMode.AUTO,
}

# Reverse mapping: Madoka OperationMode -> HA HVACMode
DAIKIN_TO_HA_MODE = {v: k for k, v in HA_MODE_TO_DAIKIN.items()}

# Fan speed mapping: HA fan mode string <-> Madoka FanSpeed enum.
HA_FAN_TO_DAIKIN = {
    FAN_AUTO: FanSpeed.AUTO,
    FAN_LOW: FanSpeed.LOW,
    FAN_MEDIUM: FanSpeed.MID,
    FAN_HIGH: FanSpeed.HIGH,
}

DAIKIN_TO_HA_FAN = {v: k for k, v in HA_FAN_TO_DAIKIN.items()}

# Map Madoka operation mode to the corresponding HA HVAC action.
# Used to show what the unit is actually doing (heating, cooling, etc.).
DAIKIN_TO_HA_ACTION = {
    OperationMode.FAN: HVACAction.FAN,
    OperationMode.DRY: HVACAction.DRYING,
    OperationMode.COOL: HVACAction.COOLING,
    OperationMode.HEAT: HVACAction.HEATING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daikin climate based on config_entry."""
    coordinator: MadokaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DaikinMadokaClimate(coordinator, entry)])


class DaikinMadokaClimate(CoordinatorEntity[MadokaCoordinator], ClimateEntity):
    """Representation of a Daikin Madoka HVAC."""

    _attr_icon = "mdi:air-conditioner"
    _attr_has_entity_name = True
    _attr_name = "Climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    def __init__(
        self, coordinator: MadokaCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_unique_id = f"{self._address}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._address)},
            "name": f"Madoka {self._address}",
            "manufacturer": "DAIKIN",
            "model": "BRC1H",
        }

    # ─── State properties ────────────────────────────────────────
    @property
    def _state(self) -> MadokaState:
        return self.coordinator.state

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def current_temperature(self) -> float | None:
        return self._state.indoor_temperature

    @property
    def target_temperature(self) -> float | None:
        if self._state.operation_mode == OperationMode.HEAT:
            return self._state.heating_setpoint
        return self._state.cooling_setpoint

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._state.power_on is False:
            return HVACMode.OFF
        if self._state.operation_mode is None:
            return None
        return DAIKIN_TO_HA_MODE.get(self._state.operation_mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._state.power_on is False:
            return HVACAction.OFF
        mode = self._state.operation_mode
        if mode is None:
            return None
        if mode == OperationMode.AUTO:
            t = self.target_temperature
            c = self.current_temperature
            if t is not None and c is not None:
                return HVACAction.HEATING if t >= c else HVACAction.COOLING
            return HVACAction.IDLE
        return DAIKIN_TO_HA_ACTION.get(mode, HVACAction.IDLE)

    @property
    def fan_mode(self) -> str | None:
        if self._state.operation_mode == OperationMode.HEAT:
            fs = self._state.heating_fan_speed
        else:
            fs = self._state.cooling_fan_speed
        if fs is None:
            return None
        return DAIKIN_TO_HA_FAN.get(fs, FAN_AUTO)

    # ─── Commands ────────────────────────────────────────────────
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode.

        When turning on, we must power on FIRST and wait ~1s before
        sending the mode command. The BRC1H firmware ignores mode
        changes while the unit is off.
        """
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_power(False)
        else:
            # Power ON first, then set mode (device ignores mode changes while off)
            if not self._state.power_on:
                await self.coordinator.async_set_power(True)
                await asyncio.sleep(1.0)
            daikin_mode = HA_MODE_TO_DAIKIN.get(hvac_mode)
            if daikin_mode is not None:
                await self.coordinator.async_set_mode(daikin_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature.

        The Madoka maintains separate cooling and heating setpoints.
        This method updates the relevant one based on the current
        operation mode, and keeps the other in sync.
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp = round(temp)
        cool = (
            self._state.cooling_setpoint
            if self._state.cooling_setpoint is not None
            else temp
        )
        heat = (
            self._state.heating_setpoint
            if self._state.heating_setpoint is not None
            else temp
        )
        if self._state.operation_mode == OperationMode.HEAT:
            heat = temp
        elif self._state.operation_mode == OperationMode.COOL:
            cool = temp
        else:
            cool = temp
            heat = temp
        await self.coordinator.async_set_setpoint(cool, heat)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed.

        The Madoka has separate cooling/heating fan speeds.
        We set both to the same value for simplicity.
        """
        daikin_fan = HA_FAN_TO_DAIKIN.get(fan_mode, FanSpeed.AUTO)
        await self.coordinator.async_set_fan(daikin_fan, daikin_fan)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_power(False)
