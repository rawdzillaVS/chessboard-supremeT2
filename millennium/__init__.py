"""
Millennium chessboard interface package.

Provides a Python interface for communicating with Millennium electronic
chessboards via the ChessLink serial protocol (38400 baud, 7E1).

Typical usage::

    from millennium import MillenniumBoard

    with MillenniumBoard("/dev/ttyUSB0") as board:
        board.on_move(lambda m: print(f"Move: {m}"))
        board.start_polling()
        input("Press Enter to quit…")
"""

from .board import MillenniumBoard
from .move_detector import BoardState, Move, MoveDetector
from .protocol import (
    ProtocolError,
    SQUARE_NAMES,
    SQUARE_INDEX,
    PIECE_NAMES,
    WHITE_PIECES,
    BLACK_PIECES,
    EMPTY_SQUARE,
    compute_checksum,
    verify_checksum,
    build_command,
    parse_status_reply,
    parse_version_reply,
)

__all__ = [
    "MillenniumBoard",
    "BoardState",
    "Move",
    "MoveDetector",
    "ProtocolError",
    "SQUARE_NAMES",
    "SQUARE_INDEX",
    "PIECE_NAMES",
    "WHITE_PIECES",
    "BLACK_PIECES",
    "EMPTY_SQUARE",
    "compute_checksum",
    "verify_checksum",
    "build_command",
    "parse_status_reply",
    "parse_version_reply",
]
