"""Platform for the Daikin AC."""
import asyncio
from datetime import timedelta
import logging

from pymadoka import Controller, discover_devices, force_device_disconnect
from pymadoka import ConnectionException
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE,
    CONF_DEVICES,
    CONF_FORCE_UPDATE,
    CONF_SCAN_INTERVAL,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant

from . import config_flow  # noqa: F401
from .const import CONTROLLERS, DOMAIN, VENTILATION_CONTROLLERS
from .ventilation import Ventilation

PARALLEL_UPDATES = 0
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

COMPONENT_TYPES = ["climate", "fan", "select"]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    vol.All(
        cv.deprecated(DOMAIN),
        {
            DOMAIN: vol.Schema(
                {
                    vol.Required(CONF_DEVICES, default=[]): vol.All(
                        cv.ensure_list, [cv.string]
                    ),
                    vol.Optional(CONF_FORCE_UPDATE, default=True): bool,
                    vol.Optional(CONF_DEVICE, default="hci0"): cv.string,
                    vol.Optional(CONF_SCAN_INTERVAL, default=5): cv.positive_int,
                }
            )
        },
    ),
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up the component."""

    hass.data.setdefault(DOMAIN, {})

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Pass conf to all the components."""

    controllers = {}
    for device in entry.data[CONF_DEVICES]:
        if entry.data[CONF_FORCE_UPDATE]:
            await force_device_disconnect(device)
        controllers[device] = Controller(device, adapter=entry.data[CONF_DEVICE])

    await discover_devices(
        adapter=entry.data[CONF_DEVICE], timeout=entry.data[CONF_SCAN_INTERVAL]
    )

    ventilation_controllers = set()

    for device, controller in controllers.items():
        try:
            await asyncio.wait_for(controller.start(), timeout=10)
        except ConnectionAbortedError as connection_aborted_error:
            _LOGGER.error(
                "Could not connect to device %s: %s",
                device,
                str(connection_aborted_error),
            )
            continue

        # Probe for ventilation support by attempting a ventilation query
        try:
            controller.ventilation = Ventilation(controller.connection)
            await asyncio.wait_for(controller.ventilation.query(), timeout=10)
            ventilation_controllers.add(device)
            _LOGGER.info("Device %s detected as ventilation unit", device)
        except (ConnectionAbortedError, ConnectionException, Exception):
            # Not a ventilation device - remove the feature so update() skips it
            if hasattr(controller, "ventilation"):
                del controller.ventilation
            _LOGGER.debug("Device %s is not a ventilation unit", device)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        CONTROLLERS: controllers,
        VENTILATION_CONTROLLERS: ventilation_controllers,
    }
    for component in COMPONENT_TYPES:
        coroutine = hass.config_entries.async_forward_entry_setups(entry, [component])
        hass.async_create_task(coroutine)


    return True


async def async_unload_entry(hass, config_entry):
    """Unload a config entry."""
    await asyncio.wait(
        [
            hass.async_create_task(hass.config_entries.async_forward_entry_unload(config_entry, component))
            for component in COMPONENT_TYPES
        ]
    )
    hass.data[DOMAIN].pop(config_entry.entry_id)

    return True
