"""
ChessLink serial protocol helpers for the Millennium chessboard.

Serial parameters: 38400 baud, 7-bit, odd parity, 1 stop bit.
All data is printable ASCII terminated with a 2-hex-digit XOR block-parity byte.

Protocol reference: magic-board.md (Dave Woodfield, 25/10/17)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Piece codes
# ---------------------------------------------------------------------------

WHITE_PIECES = frozenset("KQRBNP")
BLACK_PIECES = frozenset("kqrbnp")
EMPTY_SQUARE = "."
ALL_PIECE_CODES = WHITE_PIECES | BLACK_PIECES | frozenset(EMPTY_SQUARE)

PIECE_NAMES: dict[str, str] = {
    "K": "white king",
    "Q": "white queen",
    "R": "white rook",
    "B": "white bishop",
    "N": "white knight",
    "P": "white pawn",
    "k": "black king",
    "q": "black queen",
    "r": "black rook",
    "b": "black bishop",
    "n": "black knight",
    "p": "black pawn",
    ".": "empty",
}

# ---------------------------------------------------------------------------
# Board square ordering
# The board sends 64 piece codes in the order A8…H8, A7…H7, …, A1…H1.
# Index 0  = A8, index 7 = H8, index 56 = A1, index 63 = H1.
# ---------------------------------------------------------------------------

FILES = "ABCDEFGH"
RANKS = "87654321"

SQUARE_NAMES: list[str] = [
    f"{FILES[col]}{RANKS[row]}" for row in range(8) for col in range(8)
]  # e.g. ['A8','B8',...,'H1']

SQUARE_INDEX: dict[str, int] = {sq: i for i, sq in enumerate(SQUARE_NAMES)}

# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def compute_checksum(payload: bytes) -> bytes:
    """Return 2-byte ASCII hex XOR checksum over *payload*."""
    chk = 0
    for b in payload:
        chk ^= b
    return format(chk, "02X").encode("ascii")


def verify_checksum(message: bytes) -> bool:
    """Return True when the last 2 bytes of *message* are the valid checksum."""
    if len(message) < 2:
        return False
    body, received = message[:-2], message[-2:]
    return compute_checksum(body) == received


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


def build_command(cmd: str, data: str = "") -> bytes:
    """Build a complete command frame including checksum."""
    payload = (cmd + data).encode("ascii")
    return payload + compute_checksum(payload)


# Convenience builders for each supported command.


def cmd_status() -> bytes:
    """'S' – request full board status."""
    return build_command("S")


def cmd_version() -> bytes:
    """'V' – request firmware version."""
    return build_command("V")


def cmd_reset() -> bytes:
    """'T' – hardware reset (no reply expected)."""
    return build_command("T")


def cmd_extinguish_leds() -> bytes:
    """'X' – turn off all 81 LEDs."""
    return build_command("X")


def cmd_set_leds(slot_time: int, led_codes: list[int]) -> bytes:
    """'L' – set LED flash pattern.

    Parameters
    ----------
    slot_time:
        Time slot duration in units of 4.096 ms (2 hex digits).
    led_codes:
        List of 81 LED pattern bytes (one per LED, index 0 = A8 corner,
        index 80 = H1 corner).
    """
    if len(led_codes) != 81:
        raise ValueError(f"led_codes must contain exactly 81 values, got {len(led_codes)}")
    if not (0 <= slot_time <= 255):
        raise ValueError(f"slot_time must be 0–255, got {slot_time}")
    data = format(slot_time, "02X") + "".join(format(v & 0xFF, "02X") for v in led_codes)
    return build_command("L", data)


def cmd_read_eeprom(address: int) -> bytes:
    """'R' – read one byte from EEPROM at *address*."""
    if not (0 <= address <= 255):
        raise ValueError(f"address must be 0–255, got {address}")
    return build_command("R", format(address, "02X"))


def cmd_write_eeprom(address: int, value: int) -> bytes:
    """'W' – write *value* to EEPROM at *address*."""
    if not (0 <= address <= 255):
        raise ValueError(f"address must be 0–255, got {address}")
    if not (0 <= value <= 255):
        raise ValueError(f"value must be 0–255, got {value}")
    return build_command("W", format(address, "02X") + format(value, "02X"))


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------


class ProtocolError(Exception):
    """Raised when a board response cannot be parsed."""


def parse_status_reply(reply: bytes) -> list[str]:
    """Parse a status reply and return the 64-element piece-code list.

    The raw reply format is: ``s<64 piece codes><2-byte checksum>``.
    The leading ``s`` is typically already stripped by the reader; if it is
    present it is ignored automatically.

    Returns
    -------
    list[str]
        64 piece codes in board order (index 0 = A8 … index 63 = H1).
    """
    if not verify_checksum(reply):
        raise ProtocolError("Checksum mismatch in status reply")
    # Strip the trailing 2-byte checksum.
    body = reply[:-2].decode("ascii", errors="replace")
    # Strip optional leading 's' acknowledgement character.
    if body.startswith("s"):
        body = body[1:]
    if len(body) != 64:
        raise ProtocolError(
            f"Expected 64 piece codes in status reply, got {len(body)}: {body!r}"
        )
    for ch in body:
        if ch not in ALL_PIECE_CODES:
            raise ProtocolError(f"Unknown piece code {ch!r} in status reply")
    return list(body)


def parse_version_reply(reply: bytes) -> str:
    """Parse a version reply and return a human-readable version string.

    Raw reply format: ``v<high 2 hex><low 2 hex><2-byte checksum>``.
    """
    if not verify_checksum(reply):
        raise ProtocolError("Checksum mismatch in version reply")
    body = reply[:-2].decode("ascii", errors="replace")
    if body.startswith("v"):
        body = body[1:]
    if len(body) != 4:
        raise ProtocolError(f"Unexpected version reply length: {body!r}")
    high = int(body[:2], 16)
    low = int(body[2:], 16)
    return f"{high}.{low}"


def parse_eeprom_reply(reply: bytes) -> tuple[int, int]:
    """Parse an EEPROM read/write reply.

    Raw format: ``[r|w]<addr 2 hex><value 2 hex><2-byte checksum>``.

    Returns
    -------
    (address, value)
    """
    if not verify_checksum(reply):
        raise ProtocolError("Checksum mismatch in EEPROM reply")
    body = reply[:-2].decode("ascii", errors="replace")
    if body and body[0] in ("r", "w"):
        body = body[1:]
    if len(body) != 4:
        raise ProtocolError(f"Unexpected EEPROM reply length: {body!r}")
    address = int(body[:2], 16)
    value = int(body[2:], 16)
    return address, value
