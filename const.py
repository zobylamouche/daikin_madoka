"""Constants for the Daikin Madoka integration."""

# Home Assistant integration domain — must match the folder name
# and the "domain" field in manifest.json.
DOMAIN = "daikin_madoka"

# Human-readable name shown in the HA UI during config flow.
TITLE = "Daikin Madoka"

# Temperature range supported by the BRC1H hardware (°C).
MIN_TEMP = 16
MAX_TEMP = 32

# Bluetooth adapter (MAC) to use for the connection, or None for any.
# The BRC1H only accepts a connection from an adapter it is BONDED to,
# and pairing fails on cheap CSR/Sena USB dongles. Pin the adapter that
# holds the bond here (per-install setting).
PREFERRED_ADAPTER = "00:01:95:57:61:61"  # Sena USB dongle (hci0) — bonded device
