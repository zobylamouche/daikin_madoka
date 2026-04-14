"""Support for Daikin VAM-FC9 ventilation fan control."""
import logging

from pymadoka import ConnectionException, Controller, PowerStateStatus
from pymadoka.connection import ConnectionStatus

from homeassistant.components.fan import FanEntity, FanEntityFeature

from . import DOMAIN
from .const import CONTROLLERS, VENTILATION_CONTROLLERS
from .ventilation import VentilationRateEnum, VentilationStatus

_LOGGER = logging.getLogger(__name__)

RATE_TO_PRESET = {
    VentilationRateEnum.AUTO: "auto",
    VentilationRateEnum.LOW: "low",
    VentilationRateEnum.HIGH: "high",
}

PRESET_TO_RATE = {v: k for k, v in RATE_TO_PRESET.items()}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Daikin ventilation fan based on config_entry."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return

    ventilation_devices = hass.data[DOMAIN][entry.entry_id].get(
        VENTILATION_CONTROLLERS, set()
    )
    if not ventilation_devices:
        return

    entities = []
    for address, controller in hass.data[DOMAIN][entry.entry_id][CONTROLLERS].items():
        if address in ventilation_devices:
            entities.append(DaikinMadokaVentilationFan(controller))

    async_add_entities(entities, update_before_add=True)


class DaikinMadokaVentilationFan(FanEntity):
    """Representation of a Daikin VAM-FC9 ventilation fan."""

    def __init__(self, controller: Controller):
        """Initialize the ventilation fan."""
        self.controller = controller

    @property
    def supported_features(self):
        """Return supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    @property
    def available(self):
        """Return the availability."""
        return (
            self.controller.connection.connection_status == ConnectionStatus.CONNECTED
        )

    @property
    def name(self):
        """Return the name of the fan."""
        base_name = (
            self.controller.connection.name
            if self.controller.connection.name is not None
            else self.controller.connection.address
        )
        return f"{base_name} Ventilation"

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self.controller.connection.address}_ventilation_fan"

    @property
    def is_on(self):
        """Return true if the fan is on."""
        if self.controller.power_state.status is None:
            return None
        return self.controller.power_state.status.turn_on

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        if not hasattr(self.controller, "ventilation") or self.controller.ventilation.status is None:
            return None
        return RATE_TO_PRESET.get(self.controller.ventilation.status.ventilation_rate)

    @property
    def preset_modes(self):
        """Return the list of available preset modes."""
        return list(PRESET_TO_RATE.keys())

    async def async_set_preset_mode(self, preset_mode: str):
        """Set the ventilation rate preset mode."""
        try:
            rate = PRESET_TO_RATE.get(preset_mode)
            if rate is None:
                return

            current_mode = self.controller.ventilation.status.ventilation_mode
            await self.controller.ventilation.update(
                VentilationStatus(current_mode, rate)
            )
            self.async_schedule_update_ha_state()
        except ConnectionAbortedError:
            _LOGGER.warning(
                "Could not set ventilation rate on %s. "
                "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    async def async_turn_on(self, **kwargs):
        """Turn the ventilation unit on."""
        try:
            await self.controller.power_state.update(PowerStateStatus(True))
        except ConnectionAbortedError:
            _LOGGER.warning(
                "Could not turn on %s. "
                "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    async def async_turn_off(self, **kwargs):
        """Turn the ventilation unit off."""
        try:
            await self.controller.power_state.update(PowerStateStatus(False))
        except ConnectionAbortedError:
            _LOGGER.warning(
                "Could not turn off %s. "
                "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    async def async_update(self):
        """Retrieve latest state."""
        try:
            if hasattr(self.controller, "ventilation"):
                await self.controller.ventilation.query()
        except ConnectionAbortedError:
            _LOGGER.warning(
                "Could not update ventilation status for %s. "
                "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    @property
    def device_info(self):
        """Return a device description for device registry."""
        return {
            "identifiers": {(DOMAIN, self.controller.connection.address)},
            "name": self.controller.connection.name or self.controller.connection.address,
            "manufacturer": "DAIKIN",
            "model": "VAM-FC9",
            "via_device": (DOMAIN, self.controller.connection.address),
        }
