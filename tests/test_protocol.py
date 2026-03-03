"""
Unit tests for millennium.protocol
"""

import pytest
from millennium.protocol import (
    ALL_PIECE_CODES,
    SQUARE_NAMES,
    SQUARE_INDEX,
    compute_checksum,
    verify_checksum,
    build_command,
    cmd_status,
    cmd_version,
    cmd_reset,
    cmd_extinguish_leds,
    cmd_set_leds,
    cmd_read_eeprom,
    cmd_write_eeprom,
    parse_status_reply,
    parse_version_reply,
    parse_eeprom_reply,
    ProtocolError,
)


# ---------------------------------------------------------------------------
# Square helpers
# ---------------------------------------------------------------------------


def test_square_names_length():
    assert len(SQUARE_NAMES) == 64


def test_square_names_order():
    assert SQUARE_NAMES[0] == "A8"
    assert SQUARE_NAMES[7] == "H8"
    assert SQUARE_NAMES[56] == "A1"
    assert SQUARE_NAMES[63] == "H1"


def test_square_index_round_trip():
    for name in SQUARE_NAMES:
        assert SQUARE_NAMES[SQUARE_INDEX[name]] == name


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------


def test_compute_checksum_single_byte():
    # XOR of just 0x53 ('S') = 0x53
    assert compute_checksum(b"S") == b"53"


def test_compute_checksum_empty():
    assert compute_checksum(b"") == b"00"


def test_compute_checksum_two_bytes():
    # ord('V') = 0x56, ord('3') = 0x33 -> XOR = 0x65
    assert compute_checksum(b"V3") == b"65"


def test_verify_checksum_valid():
    payload = b"S"
    chk = compute_checksum(payload)
    assert verify_checksum(payload + chk) is True


def test_verify_checksum_invalid():
    assert verify_checksum(b"SXX") is False


def test_verify_checksum_too_short():
    assert verify_checksum(b"S") is False
    assert verify_checksum(b"") is False


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


def test_cmd_status():
    frame = cmd_status()
    # Should start with 'S' and end with valid checksum
    assert frame[:1] == b"S"
    assert verify_checksum(frame)


def test_cmd_version():
    frame = cmd_version()
    assert frame[:1] == b"V"
    assert verify_checksum(frame)


def test_cmd_reset():
    frame = cmd_reset()
    assert frame[:1] == b"T"
    assert verify_checksum(frame)


def test_cmd_extinguish_leds():
    frame = cmd_extinguish_leds()
    assert frame[:1] == b"X"
    assert verify_checksum(frame)


def test_cmd_set_leds_valid():
    frame = cmd_set_leds(10, [0x00] * 81)
    assert frame[:1] == b"L"
    assert verify_checksum(frame)


def test_cmd_set_leds_wrong_count():
    with pytest.raises(ValueError, match="81"):
        cmd_set_leds(10, [0xFF] * 64)


def test_cmd_set_leds_slot_time_out_of_range():
    with pytest.raises(ValueError):
        cmd_set_leds(256, [0x00] * 81)


def test_cmd_read_eeprom():
    frame = cmd_read_eeprom(0)
    assert frame[:1] == b"R"
    assert verify_checksum(frame)


def test_cmd_write_eeprom():
    frame = cmd_write_eeprom(2, 0x03)
    assert frame[:1] == b"W"
    assert verify_checksum(frame)


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------


def _make_status_reply(codes: str, include_ack: bool = True) -> bytes:
    """Build a well-formed status reply byte string."""
    body = ("s" if include_ack else "") + codes
    raw = body.encode("ascii")
    return raw + compute_checksum(raw)


def test_parse_status_reply_initial_position():
    # Standard initial board: back ranks + pawns + empty middle
    back_black = "rnbqkbnr"
    pawns_black = "pppppppp"
    empty = "." * 8
    pawns_white = "PPPPPPPP"
    back_white = "RNBQKBNR"
    board_str = back_black + pawns_black + empty + empty + empty + empty + pawns_white + back_white
    assert len(board_str) == 64
    reply = _make_status_reply(board_str)
    codes = parse_status_reply(reply)
    assert len(codes) == 64
    assert codes[0] == "r"
    assert codes[4] == "k"
    assert codes[56] == "R"
    assert codes[60] == "K"


def test_parse_status_reply_without_ack():
    codes_str = "." * 64
    # Build reply without leading 's'
    raw = codes_str.encode("ascii")
    reply = raw + compute_checksum(raw)
    codes = parse_status_reply(reply)
    assert all(c == "." for c in codes)


def test_parse_status_reply_bad_checksum():
    codes_str = "." * 64
    raw = ("s" + codes_str).encode("ascii")
    with pytest.raises(ProtocolError, match="Checksum"):
        parse_status_reply(raw + b"XX")


def test_parse_status_reply_wrong_length():
    # Only 32 piece codes
    body = ("s" + "." * 32).encode("ascii")
    reply = body + compute_checksum(body)
    with pytest.raises(ProtocolError, match="64"):
        parse_status_reply(reply)


def test_parse_status_reply_unknown_piece():
    body = ("s" + "Z" + "." * 63).encode("ascii")
    reply = body + compute_checksum(body)
    with pytest.raises(ProtocolError, match="Unknown piece"):
        parse_status_reply(reply)


def test_parse_version_reply():
    body = b"v0201"
    reply = body + compute_checksum(body)
    version = parse_version_reply(reply)
    assert version == "2.1"


def test_parse_version_reply_bad_checksum():
    body = b"v0201"
    with pytest.raises(ProtocolError, match="Checksum"):
        parse_version_reply(body + b"ZZ")


def test_parse_eeprom_reply_read():
    body = b"r0203"
    reply = body + compute_checksum(body)
    addr, val = parse_eeprom_reply(reply)
    assert addr == 2
    assert val == 3


def test_parse_eeprom_reply_write():
    body = b"w0A0F"
    reply = body + compute_checksum(body)
    addr, val = parse_eeprom_reply(reply)
    assert addr == 10
    assert val == 15
