"""Config flow for the Daikin Madoka integration.

Supports two entry methods:
1. Bluetooth auto-discovery: HA detects devices with names matching
   UE878*, Madoka*, BRC*, Daikin* and shows a confirmation dialog.
2. Manual entry: the user types the BLE MAC address of the thermostat.

The MAC address is normalised to upper-case and used as the unique_id
to prevent duplicate config entries.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, TITLE

_LOGGER = logging.getLogger(__name__)

# Regex for validating MAC addresses (colon or dash separated).
_MAC_RE = re.compile(
    r"^[0-9a-fA-F]{2}([:-])[0-9a-fA-F]{2}(\1[0-9a-fA-F]{2}){4}$"
)

# Known BLE advertisement name prefixes for Daikin Madoka devices.
# Used during Bluetooth auto-discovery to identify compatible devices.
_KNOWN_NAMES = ("madoka", "daikin", "brc", "ue878")


def _valid_mac(mac: str) -> bool:
    """Return True if the string is a well-formed MAC address."""
    return bool(_MAC_RE.match(mac.strip()))


def _is_daikin_madoka(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Check if a discovered BLE device is likely a Daikin Madoka."""
    name = (discovery_info.name or "").lower()
    return any(n in name for n in _KNOWN_NAMES)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Daikin Madoka."""

    VERSION = 1

    def __init__(self) -> None:
        self.discovery_info: BluetoothServiceInfoBleak | None = None

    # ─── Bluetooth auto‑discovery ────────────────────────────────
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()

        if not _is_daikin_madoka(discovery_info):
            return self.async_abort(reason="not_supported")

        self.discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm Bluetooth discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=TITLE,
                data={"address": self.discovery_info.address.upper()},
            )

        name = self.discovery_info.name or self.discovery_info.address
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    # ─── Manual entry ────────────────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual MAC entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input.get("address", "").strip()

            if not mac:
                errors["address"] = "required"
            elif not _valid_mac(mac):
                errors["address"] = "invalid_mac"

            if not errors:
                address = mac.upper()
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=TITLE,
                    data={"address": address},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("address"): str}
            ),
            errors=errors,
            description_placeholders={"example": "AA:BB:CC:DD:EE:FF"},
        )


