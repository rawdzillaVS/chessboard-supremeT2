"""
Unit tests for MillenniumBoard (with a mock serial port)
"""

import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from millennium.board import MillenniumBoard
from millennium.move_detector import BoardState, Move
from millennium.protocol import (
    compute_checksum,
    parse_status_reply,
    ProtocolError,
    EMPTY_SQUARE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status_reply(codes: str) -> bytes:
    """Return a well-formed status reply for the given 64-char piece string."""
    body = ("s" + codes).encode("ascii")
    return body + compute_checksum(body)


def _make_version_reply(high: int, low: int) -> bytes:
    body = f"v{high:02X}{low:02X}".encode("ascii")
    return body + compute_checksum(body)


def _make_led_reply() -> bytes:
    body = b"l"
    return body + compute_checksum(body)


def _make_extinguish_reply() -> bytes:
    body = b"x"
    return body + compute_checksum(body)


EMPTY_BOARD_REPLY = _make_status_reply("." * 64)
INITIAL_BOARD_REPLY = _make_status_reply(
    "rnbqkbnr" + "pppppppp" + "." * 32 + "PPPPPPPP" + "RNBQKBNR"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_board_with_mock_serial(replies: list[bytes]) -> tuple[MillenniumBoard, MagicMock]:
    """Return a MillenniumBoard wired to a mock serial port."""
    mock_serial_cls = MagicMock()
    mock_port = MagicMock()
    mock_serial_cls.return_value = mock_port
    mock_port.is_open = True

    # Each call to read(1) returns successive bytes from the reply queue.
    reply_bytes: list[bytes] = []
    for reply in replies:
        reply_bytes.extend([bytes([b]) for b in reply])
    # Append a terminal empty byte so reads block gracefully at end
    reply_bytes.append(b"")

    call_idx = {"i": 0}

    def read_side_effect(n: int = 1) -> bytes:
        idx = call_idx["i"]
        if idx < len(reply_bytes):
            call_idx["i"] += 1
            return reply_bytes[idx]
        return b""

    mock_port.read.side_effect = read_side_effect

    with patch("millennium.board.serial.Serial", mock_serial_cls):
        board = MillenniumBoard("/dev/ttyFAKE")
        board.connect()

    return board, mock_port


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_opens_serial_port():
    mock_serial_cls = MagicMock()
    mock_port = MagicMock()
    mock_serial_cls.return_value = mock_port
    mock_port.is_open = True

    with patch("millennium.board.serial.Serial", mock_serial_cls):
        board = MillenniumBoard("/dev/ttyFAKE")
        board.connect()

    mock_serial_cls.assert_called_once()
    assert board.is_connected()


def test_connect_is_idempotent():
    mock_serial_cls = MagicMock()
    mock_port = MagicMock()
    mock_serial_cls.return_value = mock_port
    mock_port.is_open = True

    with patch("millennium.board.serial.Serial", mock_serial_cls):
        board = MillenniumBoard("/dev/ttyFAKE")
        board.connect()
        board.connect()  # second call should be no-op

    mock_serial_cls.assert_called_once()


def test_disconnect_closes_serial_port():
    mock_serial_cls = MagicMock()
    mock_port = MagicMock()
    mock_serial_cls.return_value = mock_port
    mock_port.is_open = True

    with patch("millennium.board.serial.Serial", mock_serial_cls):
        board = MillenniumBoard("/dev/ttyFAKE")
        board.connect()
        board.disconnect()

    mock_port.close.assert_called_once()


def test_not_connected_raises():
    board = MillenniumBoard("/dev/ttyFAKE")
    with pytest.raises(IOError, match="not connected"):
        board.get_board_state()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager():
    mock_serial_cls = MagicMock()
    mock_port = MagicMock()
    mock_serial_cls.return_value = mock_port
    mock_port.is_open = True
    mock_port.read.return_value = b""

    with patch("millennium.board.serial.Serial", mock_serial_cls):
        with MillenniumBoard("/dev/ttyFAKE") as board:
            assert board.is_connected()

    mock_port.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_board_state
# ---------------------------------------------------------------------------


def test_get_board_state_empty_board():
    board, _ = make_board_with_mock_serial([EMPTY_BOARD_REPLY])
    state = board.get_board_state()
    assert isinstance(state, BoardState)
    assert all(sq == EMPTY_SQUARE for sq in state.squares)


def test_get_board_state_initial_position():
    board, _ = make_board_with_mock_serial([INITIAL_BOARD_REPLY])
    state = board.get_board_state()
    assert state.get("E1") == "K"
    assert state.get("E8") == "k"


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------


def test_get_version():
    reply = _make_version_reply(2, 1)
    board, _ = make_board_with_mock_serial([reply])
    version = board.get_version()
    assert version == "2.1"


# ---------------------------------------------------------------------------
# extinguish_leds
# ---------------------------------------------------------------------------


def test_extinguish_leds():
    board, mock_port = make_board_with_mock_serial([_make_extinguish_reply()])
    board.extinguish_leds()
    # The write method should have been called with an 'X'-prefixed command
    written = b"".join(c.args[0] for c in mock_port.write.call_args_list)
    assert written[0:1] == b"X"


# ---------------------------------------------------------------------------
# highlight_squares
# ---------------------------------------------------------------------------


def test_highlight_squares_valid():
    board, mock_port = make_board_with_mock_serial([_make_led_reply()])
    board.highlight_squares(["E2", "E4"])
    written = b"".join(c.args[0] for c in mock_port.write.call_args_list)
    assert written[0:1] == b"L"


def test_highlight_squares_unknown_square():
    board, _ = make_board_with_mock_serial([])
    with pytest.raises(ValueError, match="Unknown square"):
        board.highlight_squares(["Z9"])


# ---------------------------------------------------------------------------
# Polling & callbacks
# ---------------------------------------------------------------------------


def test_on_move_callback_triggered():
    from millennium.protocol import SQUARE_INDEX

    # First reply = initial board; second reply = pawn moved E2→E4
    squares2 = list("rnbqkbnr" + "pppppppp" + "." * 32 + "PPPPPPPP" + "RNBQKBNR")
    squares2[SQUARE_INDEX["E2"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["E4"]] = "P"
    second_reply = _make_status_reply("".join(squares2))

    board, _ = make_board_with_mock_serial([INITIAL_BOARD_REPLY, second_reply])

    # Seed detector with the first board state so the second triggers a move
    first_state = board.get_board_state()
    board._move_detector.reset(first_state)

    received: list[Move] = []
    board.on_move(received.append)

    # Manually trigger one poll cycle
    new_state = board.get_board_state()
    moves = board._move_detector.update(new_state)
    for m in moves:
        for cb in board._move_callbacks:
            cb(m)

    assert len(received) == 1
    assert received[0].from_square == "E2"
    assert received[0].to_square == "E4"
