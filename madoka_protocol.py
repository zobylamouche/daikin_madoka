"""
madoka_protocol.py — Daikin Madoka BRC1H BLE protocol implementation.

Implements the TLV chunked protocol reverse-engineered from the device.
No dependency on pymadoka; this is a clean-room reimplementation based on
the documented GATT protocol.

Wire format (per chunk, max 20 bytes):
  [chunk_id (1B)] [payload (up to 19B)]

First chunk payload starts with total-payload-length byte.

Command payload:
  [total_len (1B)] [0x00 (1B)] [cmd_id_hi (1B)] [cmd_id_lo (1B)] [TLV args...]

TLV argument:
  [param_id (1B)] [param_size (1B)] [param_value (variable)]
  param_size=0xFF means no value (size 0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

# ─── BLE UUIDs ───────────────────────────────────────────────
SERVICE_UUID = "2141e110-213a-11e6-b67b-9e71128cae77"
NOTIFY_CHAR_UUID = "2141e111-213a-11e6-b67b-9e71128cae77"
WRITE_CHAR_UUID = "2141e112-213a-11e6-b67b-9e71128cae77"

MAX_CHUNK_SIZE = 20  # BLE ATT MTU limit


# ─── Enums ───────────────────────────────────────────────────
class OperationMode(Enum):
    FAN = 0
    DRY = 1
    AUTO = 2
    COOL = 3
    HEAT = 4


class FanSpeed(Enum):
    AUTO = 0
    LOW = 1
    MID = 3
    HIGH = 5


# ─── Command IDs ─────────────────────────────────────────────
# Get commands
CMD_GET_POWER = 0x0020
CMD_GET_MODE = 0x0030
CMD_GET_SETPOINT = 0x0040
CMD_GET_FAN = 0x0050
CMD_GET_TEMPERATURES = 0x0110

CMD_GET_CLEAN_FILTER = 0x0100
CMD_GET_VERSION = 0x0130
CMD_GET_EYE_BRIGHTNESS = 0x0302

# Set commands (add 0x4000 to Get)
CMD_SET_POWER = 0x4020
CMD_SET_MODE = 0x4030
CMD_SET_SETPOINT = 0x4040
CMD_SET_FAN = 0x4050
CMD_RESET_FILTER = 0x4220
CMD_SET_EYE_BRIGHTNESS = 0x4302

# TLV parameter IDs
PARAM_POWER = 0x20
PARAM_MODE = 0x20
PARAM_SETPOINT_COOLING = 0x20
PARAM_SETPOINT_HEATING = 0x21
PARAM_FAN_COOLING = 0x20
PARAM_FAN_HEATING = 0x21
PARAM_TEMP_INDOOR = 0x40
PARAM_TEMP_OUTDOOR = 0x41

# Extended feature param IDs
PARAM_CLEAN_FILTER = 0x62
PARAM_VERSION_RC = 0x45
PARAM_VERSION_BLE = 0x46
PARAM_EYE_BRIGHTNESS = 0x33


# ─── Data Classes ────────────────────────────────────────────
@dataclass
class MadokaState:
    """Current state of the Madoka thermostat."""
    power_on: Optional[bool] = None
    operation_mode: Optional[OperationMode] = None
    indoor_temperature: Optional[float] = None
    outdoor_temperature: Optional[float] = None
    cooling_setpoint: Optional[float] = None
    heating_setpoint: Optional[float] = None
    cooling_fan_speed: Optional[FanSpeed] = None
    heating_fan_speed: Optional[FanSpeed] = None
    # Extended features
    clean_filter_needed: Optional[bool] = None
    firmware_rc: Optional[str] = None
    firmware_ble: Optional[str] = None
    eye_brightness: Optional[int] = None


# ─── Chunking ────────────────────────────────────────────────
def split_payload_to_chunks(payload: bytes) -> list[bytes]:
    """Split a command payload into BLE chunks (max 20 bytes each)."""
    data = bytearray(payload)
    chunks: list[bytes] = []
    idx = 0
    while True:
        start = idx * 19
        end = min(start + 19, len(data))
        chunk = bytearray([idx]) + data[start:end]
        chunks.append(bytes(chunk))
        idx += 1
        if end >= len(data):
            break
    return chunks


class ChunkAssembler:
    """Reassemble incoming BLE notification chunks into complete messages."""

    def __init__(self) -> None:
        self._chunks: dict[int, bytes] = {}
        self._expected_length: int = 0

    def add_chunk(self, data: bytes) -> Optional[bytes]:
        """Add a chunk. Returns complete payload if message is complete, else None."""
        if len(data) < 2:
            return None

        chunk_id = data[0]

        # If chunk_id <= last chunk_id and we have data, new message started
        if chunk_id == 0:
            self._chunks.clear()
            self._expected_length = data[1]  # first payload byte = total length
            self._chunks[0] = data[1:]  # skip chunk_id
        else:
            self._chunks[chunk_id] = data[1:]

        # Check if complete
        expected_chunks = math.ceil(self._expected_length / 19)
        if expected_chunks > 0 and len(self._chunks) >= expected_chunks:
            # Reassemble in order
            result = bytearray()
            for i in range(expected_chunks):
                if i in self._chunks:
                    result.extend(self._chunks[i])
            self._chunks.clear()
            return bytes(result)

        return None


# ─── Command Building ────────────────────────────────────────
def build_command(cmd_id: int, params: Optional[Dict[int, bytes]] = None) -> bytes:
    """Build a complete command payload (before chunking).

    Format: [total_len] [0x00] [cmd_hi] [cmd_lo] [TLV params...]
    """
    tlv = bytearray()
    if params:
        for param_id, value in params.items():
            tlv.append(param_id)
            tlv.append(len(value))
            tlv.extend(value)
    else:
        tlv.extend(b"\x00\x00")

    payload = bytearray(4 + len(tlv))
    payload[0] = len(payload)       # total length
    payload[1] = 0x00               # fixed
    payload[2] = (cmd_id >> 8) & 0xFF  # cmd_id high
    payload[3] = cmd_id & 0xFF        # cmd_id low
    payload[4:] = tlv
    return bytes(payload)


def build_chunked_command(cmd_id: int, params: Optional[Dict[int, bytes]] = None) -> list[bytes]:
    """Build a command and split into BLE-ready chunks."""
    payload = build_command(cmd_id, params)
    return split_payload_to_chunks(payload)


# ─── Response Parsing ────────────────────────────────────────
def parse_response(data: bytes) -> tuple[int, Dict[int, bytes]]:
    """Parse a reassembled response payload.

    Returns (cmd_id, {param_id: value_bytes}).
    """
    if len(data) < 4:
        raise ValueError(f"Response too short: {len(data)} bytes")

    # total_length = data[0]
    cmd_id = (data[2] << 8) | data[3]

    values: Dict[int, bytes] = {}
    i = 4
    while i < len(data):
        if i + 1 >= len(data):
            break
        param_id = data[i]
        param_size = data[i + 1]
        if param_size == 0xFF:
            param_size = 0
        value = data[i + 2: i + 2 + param_size]
        if len(value) == 0:
            value = b"\x00"
        values[param_id] = value
        i += 2 + param_size

    return cmd_id, values


# ─── High-level Command Builders ─────────────────────────────
def cmd_get_power() -> list[bytes]:
    return build_chunked_command(CMD_GET_POWER)


def cmd_set_power(turn_on: bool) -> list[bytes]:
    return build_chunked_command(CMD_SET_POWER, {
        PARAM_POWER: bytes([0x01 if turn_on else 0x00]),
    })


def cmd_get_mode() -> list[bytes]:
    return build_chunked_command(CMD_GET_MODE)


def cmd_set_mode(mode: OperationMode) -> list[bytes]:
    return build_chunked_command(CMD_SET_MODE, {
        PARAM_MODE: mode.value.to_bytes(1, "big"),
    })


def cmd_get_setpoint() -> list[bytes]:
    return build_chunked_command(CMD_GET_SETPOINT)


def cmd_set_setpoint(cooling: float, heating: float) -> list[bytes]:
    """Set target temperatures (GFLOAT: value * 128, 2 bytes big-endian)."""
    return build_chunked_command(CMD_SET_SETPOINT, {
        PARAM_SETPOINT_COOLING: int(cooling * 128).to_bytes(2, "big"),
        PARAM_SETPOINT_HEATING: int(heating * 128).to_bytes(2, "big"),
        # Required padding params
        0x30: b"\x00",       # range_enabled
        0x31: b"\x02",       # mode (always 2)
        0x32: b"\x00",       # min_differential
    })


def cmd_get_fan() -> list[bytes]:
    return build_chunked_command(CMD_GET_FAN)


def cmd_set_fan(cooling: FanSpeed, heating: FanSpeed) -> list[bytes]:
    return build_chunked_command(CMD_SET_FAN, {
        PARAM_FAN_COOLING: cooling.value.to_bytes(1, "big"),
        PARAM_FAN_HEATING: heating.value.to_bytes(1, "big"),
    })


def cmd_get_temperatures() -> list[bytes]:
    return build_chunked_command(CMD_GET_TEMPERATURES)


# ─── Extended Command Builders ────────────────────────────────
def cmd_get_clean_filter() -> list[bytes]:
    return build_chunked_command(CMD_GET_CLEAN_FILTER)


def cmd_reset_filter() -> list[bytes]:
    """Disable clean filter indicator and reset timer."""
    return build_chunked_command(CMD_RESET_FILTER, {
        0x51: b"\x01",   # disable indicator
        0xFE: b"\x01",   # reset timer
    })


def cmd_get_version() -> list[bytes]:
    return build_chunked_command(CMD_GET_VERSION)


def cmd_get_eye_brightness() -> list[bytes]:
    return build_chunked_command(CMD_GET_EYE_BRIGHTNESS, {
        PARAM_EYE_BRIGHTNESS: b"\x00",
    })


def cmd_set_eye_brightness(level: int) -> list[bytes]:
    """Set eye LED brightness (0=off .. 19=max)."""
    level = max(0, min(19, level))
    return build_chunked_command(CMD_SET_EYE_BRIGHTNESS, {
        PARAM_EYE_BRIGHTNESS: level.to_bytes(1, "big"),
    })


# ─── Response Decoders ────────────────────────────────────────
def decode_power(values: Dict[int, bytes]) -> bool:
    """Decode power state response."""
    return values.get(PARAM_POWER, b"\x00")[0] == 0x01


def decode_mode(values: Dict[int, bytes]) -> Optional[OperationMode]:
    """Decode operation mode response."""
    raw = values.get(PARAM_MODE)
    if raw is None:
        return None
    try:
        return OperationMode(int.from_bytes(raw, "big"))
    except ValueError:
        return None


def decode_setpoint(values: Dict[int, bytes]) -> tuple[Optional[float], Optional[float]]:
    """Decode setpoint response. Returns (cooling, heating) in Celsius."""
    cooling = None
    heating = None
    raw_c = values.get(PARAM_SETPOINT_COOLING)
    raw_h = values.get(PARAM_SETPOINT_HEATING)
    if raw_c and len(raw_c) >= 2:
        cooling = round(int.from_bytes(raw_c, "big") / 128.0)
    if raw_h and len(raw_h) >= 2:
        heating = round(int.from_bytes(raw_h, "big") / 128.0)
    return cooling, heating


def decode_fan(values: Dict[int, bytes]) -> tuple[Optional[FanSpeed], Optional[FanSpeed]]:
    """Decode fan speed response. Returns (cooling, heating)."""
    def _to_fan(raw: Optional[bytes]) -> Optional[FanSpeed]:
        if raw is None:
            return None
        v = int.from_bytes(raw, "big")
        if 2 <= v <= 4:
            return FanSpeed.MID
        try:
            return FanSpeed(v)
        except ValueError:
            return None

    return _to_fan(values.get(PARAM_FAN_COOLING)), _to_fan(values.get(PARAM_FAN_HEATING))


def decode_temperatures(values: Dict[int, bytes]) -> tuple[Optional[float], Optional[float]]:
    """Decode temperature response. Returns (indoor, outdoor) in Celsius."""
    indoor = None
    outdoor = None
    raw_i = values.get(PARAM_TEMP_INDOOR)
    raw_o = values.get(PARAM_TEMP_OUTDOOR)
    if raw_i:
        indoor = float(raw_i[0])
    if raw_o:
        v = raw_o[0]
        outdoor = None if v == 0xFF else float(v)
    return indoor, outdoor


# ─── Extended Response Decoders ───────────────────────────────
def decode_clean_filter(values: Dict[int, bytes]) -> bool:
    """Decode clean filter indicator. Returns True if filter needs cleaning."""
    raw = values.get(PARAM_CLEAN_FILTER, b"\x00")
    return (raw[0] & 0x01) == 1


def decode_version(values: Dict[int, bytes]) -> tuple[Optional[str], Optional[str]]:
    """Decode firmware version. Returns (rc_version, ble_version)."""
    rc = None
    ble = None
    raw_rc = values.get(PARAM_VERSION_RC)
    raw_ble = values.get(PARAM_VERSION_BLE)
    if raw_rc and len(raw_rc) >= 3:
        rc = f"{raw_rc[0]}.{raw_rc[1]}.{raw_rc[2]}"
    if raw_ble and len(raw_ble) >= 2:
        ble = f"{raw_ble[0]}.{raw_ble[1]}"
    return rc, ble


def decode_eye_brightness(values: Dict[int, bytes]) -> Optional[int]:
    """Decode eye brightness level (0-19)."""
    raw = values.get(PARAM_EYE_BRIGHTNESS)
    if raw is None:
        return None
    return raw[0]
