"""
coordinator.py — DataUpdateCoordinator for Daikin Madoka BRC1H.

This is the central data manager for the integration.  It:
1.  Owns the MadokaBluetoothClient (BLE connection layer).
2.  Polls the thermostat every 60 seconds, querying each feature
    in sequence with a short pause between queries to avoid
    overwhelming the BLE link.
3.  Stores the current state in a MadokaState dataclass.
4.  Exposes async_set_* methods that send write commands to the
    device and immediately update the local state so the UI
    reflects changes without waiting for the next poll.

Query order per poll cycle:
  1. Power state           (CMD 0x0020)
  2. Operation mode        (CMD 0x0030)
  3. Setpoints (cool/heat) (CMD 0x0040)
  4. Fan speeds            (CMD 0x0050)
  5. Temperatures (in/out) (CMD 0x0110)
  6. Clean filter flag     (CMD 0x0100)
  7. Firmware version      (CMD 0x0130) — only fetched once
  8. Eye LED brightness    (CMD 0x0302)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
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
    CMD_SET_SETPOINT,
    CMD_GET_FAN,
    CMD_GET_TEMPERATURES,
    CMD_GET_CLEAN_FILTER,
    CMD_GET_VERSION,
    CMD_GET_EYE_BRIGHTNESS,
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
    cmd_get_clean_filter,
    cmd_reset_filter,
    cmd_get_version,
    cmd_get_eye_brightness,
    cmd_set_eye_brightness,
    decode_power,
    decode_mode,
    decode_setpoint,
    decode_fan,
    decode_temperatures,
    decode_clean_filter,
    decode_version,
    decode_eye_brightness,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_UPDATE_INTERVAL = timedelta(seconds=60)  # Polling interval for BLE queries
_QUERY_PAUSE = 0.5  # Seconds between sequential BLE queries to avoid congestion


class MadokaCoordinator(DataUpdateCoordinator[MadokaState]):
    """Coordinator that polls a Madoka thermostat over BLE."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Madoka {address}",
            update_interval=_UPDATE_INTERVAL,
        )
        self.address = address
        self._client = MadokaBluetoothClient(hass, address)
        self.state = MadokaState()
        self._setpoint_raw: dict = {}  # cached raw GET_SETPOINT params for SET echo

    async def async_start(self) -> None:
        """Start the BLE client and schedule first refresh."""
        await self._client.async_start()

    async def async_stop(self) -> None:
        """Stop the BLE client."""
        await self._client.async_stop()

    # ─── Polling ─────────────────────────────────────────────────
    async def _async_update_data(self) -> MadokaState:
        """Poll all features from the device.

        Each query is wrapped in its own try/except so that a failure
        in one feature (e.g. firmware version) does not prevent the
        others from being updated.  A short pause between queries
        gives the BLE stack time to process each response.
        """
        ok_count = 0  # queries that actually got an answer this cycle
        _LOGGER.info("Madoka %s: poll cycle starting", self.address)
        try:
            # 1. Power
            try:
                vals = await self._client.async_query(
                    cmd_get_power(), CMD_GET_POWER
                )
                self.state.power_on = decode_power(vals)
                ok_count += 1
            except Exception as err:
                _LOGGER.debug("Power read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 2. Operation mode
            try:
                vals = await self._client.async_query(
                    cmd_get_mode(), CMD_GET_MODE
                )
                self.state.operation_mode = decode_mode(vals)
                ok_count += 1
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
                self._setpoint_raw = vals  # cache limit params for SET command
                ok_count += 1
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
                ok_count += 1
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
                ok_count += 1
            except Exception as err:
                _LOGGER.debug("Temperature read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 6. Clean filter indicator
            try:
                vals = await self._client.async_query(
                    cmd_get_clean_filter(), CMD_GET_CLEAN_FILTER
                )
                self.state.clean_filter_needed = decode_clean_filter(vals)
                ok_count += 1
            except Exception as err:
                _LOGGER.debug("Clean filter read failed: %s", err)

            await asyncio.sleep(_QUERY_PAUSE)

            # 7. Firmware version (only fetch once)
            if self.state.firmware_rc is None:
                try:
                    vals = await self._client.async_query(
                        cmd_get_version(), CMD_GET_VERSION
                    )
                    rc, ble = decode_version(vals)
                    if rc is not None:
                        self.state.firmware_rc = rc
                    if ble is not None:
                        self.state.firmware_ble = ble
                except Exception as err:
                    _LOGGER.debug("Version read failed: %s", err)

                await asyncio.sleep(_QUERY_PAUSE)

            # 8. Eye brightness
            try:
                vals = await self._client.async_query(
                    cmd_get_eye_brightness(), CMD_GET_EYE_BRIGHTNESS
                )
                brightness = decode_eye_brightness(vals)
                if brightness is not None:
                    self.state.eye_brightness = brightness
                ok_count += 1
            except Exception as err:
                _LOGGER.debug("Eye brightness read failed: %s", err)

            if ok_count == 0:
                # Nothing answered at all: device unreachable. Marking
                # the update as failed makes entities show "unavailable"
                # instead of silently freezing on stale values.
                raise UpdateFailed(
                    f"Madoka {self.address} did not answer any query"
                )

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
    # All write methods follow the same pattern:
    #   1. Send the BLE command via the client.
    #   2. Optimistically update the local state.
    #   3. Notify HA listeners via async_set_updated_data().

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
        """Set target temperatures.

        Both cooling and heating must be equal — the BRC1H silently
        rejects any SET where they differ.  Limits from the last GET
        are echoed back so the device doesn't reject the command for
        out-of-range limit params.
        """
        try:
            await self._client.async_query(
                cmd_set_setpoint(cooling, heating, self._setpoint_raw or None),
                CMD_SET_SETPOINT,
                timeout=10.0,
            )
        except Exception as err:
            _LOGGER.warning("SET 0x4040 failed: %s", err)

        # Verify and refresh cache
        await asyncio.sleep(0.5)
        try:
            vals = await self._client.async_query(
                cmd_get_setpoint(), CMD_GET_SETPOINT
            )
            actual_cool, actual_heat = decode_setpoint(vals)
            _LOGGER.debug(
                "Setpoint verify: device cool=%s heat=%s (sent cool=%.1f heat=%.1f)",
                actual_cool, actual_heat, cooling, heating,
            )
            self.state.cooling_setpoint = actual_cool if actual_cool is not None else cooling
            self.state.heating_setpoint = actual_heat if actual_heat is not None else heating
            self._setpoint_raw = vals
        except Exception as err:
            _LOGGER.debug("Verify GET failed: %s", err)
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

    async def async_reset_filter(self) -> None:
        """Reset clean filter indicator."""
        await self._client.async_send_command(cmd_reset_filter())
        self.state.clean_filter_needed = False
        self.async_set_updated_data(self.state)

    async def async_set_eye_brightness(self, level: int) -> None:
        """Set eye LED brightness (0-19)."""
        await self._client.async_send_command(cmd_set_eye_brightness(level))
        self.state.eye_brightness = level
        self.async_set_updated_data(self.state)
