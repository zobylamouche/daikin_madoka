"""
coordinator.py — DataUpdateCoordinator for Daikin Madoka BRC1H.

Polls all device features periodically and exposes a MadokaState.
Provides methods to send set-commands to the device.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import HomeAssistantError

from .bluetooth import MadokaBluetoothClient
from .madoka_protocol import (
    CMD_GET_POWER,
    CMD_GET_MODE,
    CMD_GET_SETPOINT,
    CMD_GET_FAN,
    CMD_GET_TEMPERATURES,
    MadokaState,
    OperationMode,
    FanSpeed,
    cmd_get_power,
    cmd_get_mode,
    cmd_get_setpoint,
    cmd_get_fan,
    cmd_get_temperatures,
    cmd_set_power,
    cmd_set_mode,
    cmd_set_setpoint,
    cmd_set_fan,
    decode_power,
    decode_mode,
    decode_setpoint,
    decode_fan,
    decode_temperatures,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_UPDATE_INTERVAL = timedelta(seconds=60)
_QUERY_PAUSE = 0.5  # seconds between sequential queries


class MadokaCoordinator(DataUpdateCoordinator[MadokaState]):
    """Coordinator that polls a Madoka thermostat over BLE."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Madoka {address}",
            update_interval=_UPDATE_INTERVAL,
        )
        self.address = address
        self._client = MadokaBluetoothClient(hass, address)
        self.state = MadokaState()

    async def async_start(self) -> None:
        """Start the BLE client and schedule first refresh."""
        await self._client.async_start()

    async def async_stop(self) -> None:
        """Stop the BLE client."""
        await self._client.async_stop()

    # ─── Polling ─────────────────────────────────────────────────
    async def _async_update_data(self) -> MadokaState:
        """Poll all features from the device."""
        try:
            # 1. Power
            try:
                vals = await self._client.async_query(
                    cmd_get_power(), CMD_GET_POWER
                )
                self.state.power_on = decode_power(vals)
            except Exception as err:
                _LOGGER.debug("Power read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 2. Operation mode
            try:
                vals = await self._client.async_query(
                    cmd_get_mode(), CMD_GET_MODE
                )
                self.state.operation_mode = decode_mode(vals)
            except Exception as err:
                _LOGGER.debug("Mode read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 3. Setpoints
            try:
                vals = await self._client.async_query(
                    cmd_get_setpoint(), CMD_GET_SETPOINT
                )
                cool, heat = decode_setpoint(vals)
                if cool is not None:
                    self.state.cooling_setpoint = cool
                if heat is not None:
                    self.state.heating_setpoint = heat
            except Exception as err:
                _LOGGER.debug("Setpoint read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 4. Fan speeds
            try:
                vals = await self._client.async_query(
                    cmd_get_fan(), CMD_GET_FAN
                )
                cool_fan, heat_fan = decode_fan(vals)
                if cool_fan is not None:
                    self.state.cooling_fan_speed = cool_fan
                if heat_fan is not None:
                    self.state.heating_fan_speed = heat_fan
            except Exception as err:
                _LOGGER.debug("Fan read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 5. Temperatures
            try:
                vals = await self._client.async_query(
                    cmd_get_temperatures(), CMD_GET_TEMPERATURES
                )
                indoor, outdoor = decode_temperatures(vals)
                if indoor is not None:
                    self.state.indoor_temperature = indoor
                if outdoor is not None:
                    self.state.outdoor_temperature = outdoor
            except Exception as err:
                _LOGGER.debug("Temperature read failed: %s", err)

            _LOGGER.debug(
                "Poll complete: power=%s mode=%s cool=%.0f°C heat=%.0f°C indoor=%s outdoor=%s",
                self.state.power_on,
                self.state.operation_mode,
                self.state.cooling_setpoint or 0,
                self.state.heating_setpoint or 0,
                self.state.indoor_temperature,
                self.state.outdoor_temperature,
            )
            return self.state

        except Exception as err:
            raise UpdateFailed(f"Failed to poll Madoka: {err}") from err

    # ─── Write Commands ──────────────────────────────────────────
    async def async_set_power(self, turn_on: bool) -> None:
        """Turn the unit on or off."""
        await self._client.async_send_command(cmd_set_power(turn_on))
        self.state.power_on = turn_on
        self.async_set_updated_data(self.state)

    async def async_set_mode(self, mode: OperationMode) -> None:
        """Set the operation mode."""
        await self._client.async_send_command(cmd_set_mode(mode))
        self.state.operation_mode = mode
        self.async_set_updated_data(self.state)

    async def async_set_setpoint(
        self, cooling: float, heating: float
    ) -> None:
        """Set target temperatures."""
        await self._client.async_send_command(
            cmd_set_setpoint(cooling, heating)
        )
        self.state.cooling_setpoint = cooling
        self.state.heating_setpoint = heating
        self.async_set_updated_data(self.state)

    async def async_set_fan(
        self, cooling: FanSpeed, heating: FanSpeed
    ) -> None:
        """Set fan speeds."""
        await self._client.async_send_command(cmd_set_fan(cooling, heating))
        self.state.cooling_fan_speed = cooling
        self.state.heating_fan_speed = heating
        self.async_set_updated_data(self.state)
