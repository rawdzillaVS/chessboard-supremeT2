"""
High-level interface to the Millennium chessboard (ChessLink protocol).

Typical usage::

    from millennium import MillenniumBoard

    with MillenniumBoard("/dev/ttyUSB0") as board:
        version = board.get_version()
        print(f"Firmware version: {version}")

        board.on_move(lambda move: print(f"Move played: {move}"))
        board.start_polling()  # background thread
        input("Press Enter to stop…\\n")
        board.stop_polling()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import serial

from .move_detector import BoardState, Move, MoveDetector
from .protocol import (
    ProtocolError,
    cmd_extinguish_leds,
    cmd_read_eeprom,
    cmd_reset,
    cmd_set_leds,
    cmd_status,
    cmd_version,
    cmd_write_eeprom,
    parse_eeprom_reply,
    parse_status_reply,
    parse_version_reply,
    verify_checksum,
)

__all__ = ["MillenniumBoard", "BoardState", "Move"]

logger = logging.getLogger(__name__)

# Default serial parameters for the Millennium ChessLink module.
_BAUD_RATE = 38400
_BYTE_SIZE = serial.SEVENBITS
_PARITY = serial.PARITY_ODD
_STOP_BITS = serial.STOPBITS_ONE

# Timeouts / poll interval
_READ_TIMEOUT = 2.0   # seconds
_WRITE_TIMEOUT = 2.0  # seconds
_DEFAULT_POLL_INTERVAL = 0.1  # seconds between board polls


class MillenniumBoard:
    """Interface to a Millennium chessboard connected over a serial port.

    Parameters
    ----------
    port:
        Serial port path (e.g. ``"/dev/ttyUSB0"`` or ``"COM3"``).
    poll_interval:
        Seconds between board-state polls when :meth:`start_polling` is
        active (default 0.1 s).

    The class can be used as a context manager::

        with MillenniumBoard("/dev/ttyUSB0") as board:
            …
    """

    def __init__(
        self,
        port: str,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._port = port
        self._poll_interval = poll_interval
        self._serial: Optional[serial.Serial] = None
        self._move_detector = MoveDetector()
        self._move_callbacks: list[Callable[[Move], None]] = []
        self._state_callbacks: list[Callable[[BoardState], None]] = []
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial connection to the board."""
        if self._serial and self._serial.is_open:
            return
        self._serial = serial.Serial(
            port=self._port,
            baudrate=_BAUD_RATE,
            bytesize=_BYTE_SIZE,
            parity=_PARITY,
            stopbits=_STOP_BITS,
            timeout=_READ_TIMEOUT,
            write_timeout=_WRITE_TIMEOUT,
        )
        logger.info("Connected to Millennium board on %s", self._port)

    def disconnect(self) -> None:
        """Close the serial connection and stop any background polling."""
        self.stop_polling()
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Disconnected from Millennium board on %s", self._port)

    def is_connected(self) -> bool:
        """Return ``True`` when the serial port is open."""
        return self._serial is not None and self._serial.is_open

    def __enter__(self) -> "MillenniumBoard":
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Board commands
    # ------------------------------------------------------------------

    def get_board_state(self) -> BoardState:
        """Request and return the current :class:`~millennium.move_detector.BoardState`.

        Raises
        ------
        ProtocolError
            If the reply cannot be parsed.
        IOError
            If the board is not connected.
        """
        self._ensure_connected()
        reply = self._send_command(cmd_status())
        codes = parse_status_reply(reply)
        return BoardState.from_piece_codes(codes)

    def get_version(self) -> str:
        """Return the board firmware version string (e.g. ``"2.1"``)."""
        self._ensure_connected()
        reply = self._send_command(cmd_version())
        return parse_version_reply(reply)

    def reset(self) -> None:
        """Send a hardware reset command. The board will take ~3 s to restart.

        No reply is sent by the board after a reset.
        """
        self._ensure_connected()
        with self._lock:
            self._serial.write(cmd_reset())  # type: ignore[union-attr]
        logger.info("Board reset command sent")

    def extinguish_leds(self) -> None:
        """Turn off all 81 LEDs on the board."""
        self._ensure_connected()
        self._send_command(cmd_extinguish_leds())

    def set_leds(self, slot_time: int, led_codes: list[int]) -> None:
        """Set the LED flash pattern for all 81 LEDs.

        Parameters
        ----------
        slot_time:
            Time slot in units of 4.096 ms (0–255).
        led_codes:
            List of 81 LED pattern bytes. See protocol documentation for
            the bit-pattern semantics.
        """
        self._ensure_connected()
        self._send_command(cmd_set_leds(slot_time, led_codes))

    def highlight_squares(self, squares: list[str], slot_time: int = 10) -> None:
        """Turn on the LEDs for the given *squares* (e.g. ``["E2", "E4"]``).

        All other LEDs are extinguished.  Use :meth:`extinguish_leds` to
        clear them afterwards.

        Parameters
        ----------
        squares:
            Board square names to highlight (e.g. ``["E2", "E4"]``).
        slot_time:
            LED slot time in units of 4.096 ms (default 10 ≈ 40 ms).
        """
        from .protocol import SQUARE_INDEX

        led_codes = [0x00] * 81
        for sq in squares:
            idx = SQUARE_INDEX.get(sq.upper())
            if idx is None:
                raise ValueError(f"Unknown square {sq!r}")
            led_codes[idx] = 0xFF  # fully on
        self.set_leds(slot_time, led_codes)

    def read_eeprom(self, address: int) -> int:
        """Read one byte from EEPROM at *address* (0–255)."""
        self._ensure_connected()
        reply = self._send_command(cmd_read_eeprom(address))
        _, value = parse_eeprom_reply(reply)
        return value

    def write_eeprom(self, address: int, value: int) -> None:
        """Write *value* to EEPROM at *address* (both 0–255)."""
        self._ensure_connected()
        self._send_command(cmd_write_eeprom(address, value))

    # ------------------------------------------------------------------
    # Polling / callback API
    # ------------------------------------------------------------------

    def on_move(self, callback: Callable[[Move], None]) -> None:
        """Register *callback* to be called whenever a move is detected.

        The callback receives a single :class:`~millennium.move_detector.Move`
        argument and is invoked from the polling thread.
        """
        self._move_callbacks.append(callback)

    def on_state_change(self, callback: Callable[[BoardState], None]) -> None:
        """Register *callback* to be called whenever the board state changes.

        The callback receives the new :class:`~millennium.move_detector.BoardState`
        and is invoked from the polling thread.
        """
        self._state_callbacks.append(callback)

    def start_polling(self) -> None:
        """Start a background thread that polls the board for moves.

        Does nothing if polling is already active.
        """
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="millennium-board-poll",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("Board polling started (interval %.3f s)", self._poll_interval)

    def stop_polling(self) -> None:
        """Stop the background polling thread and wait for it to finish."""
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
        self._poll_thread = None
        logger.info("Board polling stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected():
            raise IOError("Board is not connected. Call connect() first.")

    def _send_command(self, command: bytes) -> bytes:
        """Send *command* and return the complete reply (including checksum)."""
        with self._lock:
            assert self._serial is not None
            self._serial.reset_input_buffer()
            self._serial.write(command)
            reply = self._read_reply()
        return reply

    def _read_reply(self) -> bytes:
        """Read a single reply message from the board.

        Replies are variable-length ASCII strings terminated by a 2-character
        XOR checksum.  We read until we have a message whose trailing 2 bytes
        form a valid checksum over the preceding bytes.
        """
        assert self._serial is not None
        buf = bytearray()
        deadline = time.monotonic() + _READ_TIMEOUT
        while time.monotonic() < deadline:
            byte = self._serial.read(1)
            if not byte:
                continue
            buf.extend(byte)
            # Need at least 3 bytes (1 ack + 2 checksum) to verify
            if len(buf) >= 3 and verify_checksum(bytes(buf)):
                return bytes(buf)
        raise ProtocolError(
            f"Timed out waiting for board reply; partial data: {bytes(buf)!r}"
        )

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while not self._stop_event.is_set():
            try:
                state = self.get_board_state()
                # Notify state-change listeners
                if (
                    self._move_detector.previous_state is None
                    or state != self._move_detector.previous_state
                ):
                    for cb in self._state_callbacks:
                        try:
                            cb(state)
                        except Exception:
                            logger.exception("Exception in state-change callback")

                moves = self._move_detector.update(state)
                for move in moves:
                    logger.debug("Move detected: %s", move)
                    for cb in self._move_callbacks:
                        try:
                            cb(move)
                        except Exception:
                            logger.exception("Exception in move callback")
            except ProtocolError as exc:
                logger.warning("Protocol error during poll: %s", exc)
            except Exception:
                logger.exception("Unexpected error during board poll")
            self._stop_event.wait(self._poll_interval)
