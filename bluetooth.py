"""
bluetooth.py — BLE client for Daikin Madoka using Home Assistant's native Bluetooth stack.

This module handles all low-level Bluetooth communication:
- GATT connection management with automatic reconnection and backoff
- Notification subscription on the Madoka NOTIFY characteristic
- Chunked command writing to the WRITE characteristic
- Response reassembly using ChunkAssembler from madoka_protocol.py
- Pending-response tracking via asyncio.Future for query/response patterns

Dependencies:
- bleak_retry_connector: provides BleakClientWithServiceCache and
  establish_connection() for reliable BLE connections.
- homeassistant.components.bluetooth: provides device discovery,
  advertisement callbacks, and BLE device lookup by MAC address.

The client is designed to be long-lived: it starts once and automatically
reconnects on disconnection using exponential backoff (1s, 2s, 5s, 10s, 15s).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from homeassistant.core import HomeAssistant, CALLBACK_TYPE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    BluetoothServiceInfoBleak,
    BluetoothScanningMode,
    BluetoothCallbackMatcher,
    BluetoothChange,
    async_register_callback,
)

from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    close_stale_connections,
    BLEAK_RETRY_EXCEPTIONS,
)

from .madoka_protocol import (
    NOTIFY_CHAR_UUID,
    WRITE_CHAR_UUID,
    ChunkAssembler,
    parse_response,
)

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 20.0           # Max time to wait for GATT connection
_WRITE_TIMEOUT_S = 10.0             # Max time for a single GATT write
_RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 15.0)  # Delays between retries
_SEND_MAX_TRIES = 3                 # Max write attempts before giving up


class MadokaBluetoothClient:
    """BLE client for Madoka thermostat using HA's native Bluetooth stack.

    Handles:
    - Connection/reconnection with backoff
    - GATT notification subscription
    - Chunked command sending with retry
    - Response reassembly and dispatch
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self.hass = hass
        self.address = address

        # Response callback: async fn(cmd_id, values_dict)
        self._response_cb: Optional[
            Callable[[int, dict[int, bytes]], Awaitable[None]]
        ] = None

        # BLE state
        self._client: Optional[BleakClientWithServiceCache] = None
        self._notify_started = False
        self._adv_cancel: Optional[CALLBACK_TYPE] = None

        # Reassembly
        self._assembler = ChunkAssembler()

        # Pending responses: {cmd_id: asyncio.Future}
        self._pending: dict[int, asyncio.Future] = {}

        # Concurrency
        self._conn_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._stopping = False

    # ─── Public API ──────────────────────────────────────────────
    def set_response_callback(
        self, cb: Callable[[int, dict[int, bytes]], Awaitable[None]]
    ) -> None:
        """Register an async callback for parsed responses."""
        self._response_cb = cb

    async def async_start(self) -> None:
        """Start BLE: register advertisement callback, connect, subscribe."""
        if self._adv_cancel:
            return

        _LOGGER.debug("Registering BLE callbacks for %s", self.address)

        def _on_advertisement(
            service_info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            _LOGGER.debug(
                "BLE advertisement from %s (RSSI=%s)",
                self.address,
                service_info.rssi,
            )

        self._adv_cancel = async_register_callback(
            self.hass,
            _on_advertisement,
            BluetoothCallbackMatcher(address=self.address),
            BluetoothScanningMode.ACTIVE,
        )

        await self._ensure_notify_started()

    async def async_stop(self) -> None:
        """Stop BLE: unsubscribe, disconnect."""
        self._stopping = True

        if self._adv_cancel:
            self._adv_cancel()
            self._adv_cancel = None

        await self._stop_notify_and_disconnect()

    async def async_send_command(
        self, chunks: list[bytes], timeout: float = _WRITE_TIMEOUT_S
    ) -> None:
        """Send chunked command to device (WriteNoResponse)."""
        async with self._write_lock:
            await self._ensure_connected()
            if not self._client:
                raise HomeAssistantError(
                    f"BLE client not available for {self.address}"
                )

            for attempt in range(1, _SEND_MAX_TRIES + 1):
                try:
                    for chunk in chunks:
                        await asyncio.wait_for(
                            self._client.write_gatt_char(
                                WRITE_CHAR_UUID, chunk, response=False
                            ),
                            timeout=timeout,
                        )
                    return
                except (asyncio.TimeoutError, *BLEAK_RETRY_EXCEPTIONS) as err:
                    _LOGGER.warning(
                        "Write attempt %d/%d failed for %s: %s",
                        attempt,
                        _SEND_MAX_TRIES,
                        self.address,
                        err,
                    )
                    if attempt == _SEND_MAX_TRIES:
                        raise HomeAssistantError(
                            f"Failed to write to {self.address} after {_SEND_MAX_TRIES} attempts"
                        ) from err
                    await self._handle_disconnect_and_retry()

    async def async_query(
        self, chunks: list[bytes], cmd_id: int, timeout: float = 10.0
    ) -> dict[int, bytes]:
        """Send a query command and wait for the response.

        Returns the parsed TLV values dict.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[int, bytes]] = loop.create_future()
        self._pending[cmd_id] = future

        try:
            await self.async_send_command(chunks)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise HomeAssistantError(
                f"Timeout waiting for response to cmd 0x{cmd_id:04X} from {self.address}"
            )
        finally:
            self._pending.pop(cmd_id, None)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ─── Connection Management ───────────────────────────────────
    async def _ensure_connected(self) -> None:
        """Ensure a GATT client is connected."""
        async with self._conn_lock:
            if self._client and self._client.is_connected:
                return

            ble_device = async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if not ble_device:
                raise HomeAssistantError(
                    f"BLE device {self.address} not found by HA bluetooth"
                )

            await close_stale_connections(ble_device)

            last_err: Exception | None = None
            for delay in _RECONNECT_BACKOFF_S:
                if self._stopping:
                    break
                try:
                    _LOGGER.info("Connecting to %s ...", self.address)
                    self._client = await establish_connection(
                        BleakClientWithServiceCache,
                        ble_device,
                        self.address,
                        self._on_disconnected,
                    )
                    _LOGGER.info("✅ Connected to %s", self.address)
                    return
                except (asyncio.TimeoutError, *BLEAK_RETRY_EXCEPTIONS) as err:
                    last_err = err
                    _LOGGER.warning(
                        "Connect failed (%s), retry in %.1fs",
                        type(err).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                except Exception as err:
                    last_err = err
                    _LOGGER.error("Unexpected connect error: %s", err)
                    await asyncio.sleep(1.0)

            if last_err:
                raise HomeAssistantError(
                    f"Failed to connect to {self.address}: {last_err}"
                ) from last_err

    async def _ensure_notify_started(self) -> None:
        """Start GATT notifications if not already active."""
        await self._ensure_connected()
        if not self._client:
            raise HomeAssistantError(
                f"BLE client not available for notify on {self.address}"
            )
        if self._notify_started:
            return

        try:
            await self._client.start_notify(
                NOTIFY_CHAR_UUID, self._on_raw_notification
            )
            self._notify_started = True
            _LOGGER.info(
                "📡 Subscribed to notifications on %s", self.address
            )
        except (asyncio.TimeoutError, *BLEAK_RETRY_EXCEPTIONS) as err:
            _LOGGER.warning("Start notify failed: %s", err)
            await self._handle_disconnect_and_retry()
            raise

    async def _stop_notify_and_disconnect(self) -> None:
        """Stop notifications and disconnect."""
        if self._client:
            try:
                if self._notify_started:
                    try:
                        await self._client.stop_notify(NOTIFY_CHAR_UUID)
                    except Exception:
                        pass
                await self._client.disconnect()
            except Exception:
                pass
            finally:
                self._notify_started = False
                self._client = None

    def _on_disconnected(
        self, _client: BleakClientWithServiceCache
    ) -> None:
        """Called when BLE disconnects unexpectedly."""
        if self._stopping:
            return
        _LOGGER.warning("⚠️ BLE disconnected from %s", self.address)
        self._notify_started = False
        asyncio.create_task(self._handle_disconnect_and_retry())

    async def _handle_disconnect_and_retry(self) -> None:
        """Reconnect with backoff after unexpected disconnect."""
        if self._stopping:
            return

        self._notify_started = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None

        for delay in _RECONNECT_BACKOFF_S:
            if self._stopping:
                return
            _LOGGER.debug("Reconnecting to %s in %.1fs ...", self.address, delay)
            await asyncio.sleep(delay)
            try:
                await self._ensure_notify_started()
                _LOGGER.info("🔄 Reconnected to %s", self.address)
                return
            except Exception as err:
                _LOGGER.debug("Reconnect attempt failed: %s", err)

        _LOGGER.error(
            "❌ Failed to reconnect to %s after all backoff attempts",
            self.address,
        )

    # ─── Notification Handling ───────────────────────────────────
    def _on_raw_notification(self, _handle: int, data: bytes) -> None:
        """Called when a GATT notification arrives (raw bytes)."""
        if not data:
            return

        complete = self._assembler.add_chunk(data)
        if complete is None:
            return  # Still assembling

        try:
            cmd_id, values = parse_response(complete)
        except Exception as err:
            _LOGGER.warning("Failed to parse BLE response: %s", err)
            return

        _LOGGER.debug(
            "Response from %s: cmd=0x%04X, %d params",
            self.address,
            cmd_id,
            len(values),
        )

        # Resolve pending future if any
        future = self._pending.pop(cmd_id, None)
        if future and not future.done():
            future.set_result(values)

        # Also fire generic callback
        if self._response_cb:
            asyncio.create_task(self._response_cb(cmd_id, values))
