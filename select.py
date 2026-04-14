"""Support for Daikin VAM-FC9 ventilation mode selection."""
import logging

from pymadoka import ConnectionException, Controller
from pymadoka.connection import ConnectionStatus

from homeassistant.components.select import SelectEntity

from . import DOMAIN
from .const import CONTROLLERS, VENTILATION_CONTROLLERS
from .ventilation import VentilationModeEnum, VentilationStatus

_LOGGER = logging.getLogger(__name__)

MODE_TO_OPTION = {
    VentilationModeEnum.AUTO: "auto",
    VentilationModeEnum.ERV: "erv",
    VentilationModeEnum.BYPASS: "bypass",
}

OPTION_TO_MODE = {v: k for k, v in MODE_TO_OPTION.items()}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Daikin ventilation mode select based on config_entry."""
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
            entities.append(DaikinMadokaVentilationMode(controller))

    async_add_entities(entities, update_before_add=True)


class DaikinMadokaVentilationMode(SelectEntity):
    """Representation of the ventilation mode selector (AUTO/ERV/BYPASS)."""

    def __init__(self, controller: Controller):
        """Initialize the ventilation mode select."""
        self.controller = controller

    @property
    def available(self):
        """Return the availability."""
        return (
            self.controller.connection.connection_status == ConnectionStatus.CONNECTED
        )

    @property
    def name(self):
        """Return the name of the select entity."""
        base_name = (
            self.controller.connection.name
            if self.controller.connection.name is not None
            else self.controller.connection.address
        )
        return f"{base_name} Ventilation Mode"

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self.controller.connection.address}_ventilation_mode"

    @property
    def options(self):
        """Return the list of available ventilation modes."""
        return list(OPTION_TO_MODE.keys())

    @property
    def current_option(self):
        """Return the current ventilation mode."""
        if not hasattr(self.controller, "ventilation") or self.controller.ventilation.status is None:
            return None
        return MODE_TO_OPTION.get(self.controller.ventilation.status.ventilation_mode)

    async def async_select_option(self, option: str):
        """Set the ventilation mode."""
        try:
            mode = OPTION_TO_MODE.get(option)
            if mode is None:
                return

            current_rate = self.controller.ventilation.status.ventilation_rate
            await self.controller.ventilation.update(
                VentilationStatus(mode, current_rate)
            )
            self.async_schedule_update_ha_state()
        except ConnectionAbortedError:
            _LOGGER.warning(
                "Could not set ventilation mode on %s. "
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
                "Could not update ventilation mode for %s. "
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
