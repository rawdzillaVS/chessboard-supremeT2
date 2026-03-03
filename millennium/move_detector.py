"""
Move detection for the Millennium chessboard.

Compares successive ``BoardState`` snapshots to identify the chess move
that was played between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .protocol import (
    ALL_PIECE_CODES,
    EMPTY_SQUARE,
    PIECE_NAMES,
    SQUARE_NAMES,
    WHITE_PIECES,
    BLACK_PIECES,
    ProtocolError,
)


# ---------------------------------------------------------------------------
# BoardState
# ---------------------------------------------------------------------------


@dataclass
class BoardState:
    """Snapshot of all 64 squares on the Millennium chessboard.

    Squares are stored in board order: index 0 = A8, index 63 = H1.
    Each entry is one of ``K Q R B N P`` (white), ``k q r b n p`` (black),
    or ``.`` (empty).
    """

    squares: list[str]

    def __post_init__(self) -> None:
        if len(self.squares) != 64:
            raise ValueError(f"BoardState requires exactly 64 squares, got {len(self.squares)}")
        for sq in self.squares:
            if sq not in ALL_PIECE_CODES:
                raise ValueError(f"Invalid piece code {sq!r}")

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_piece_codes(cls, codes: list[str]) -> "BoardState":
        """Create a ``BoardState`` from the 64-element piece-code list
        returned by :func:`~millennium.protocol.parse_status_reply`."""
        return cls(squares=list(codes))

    @classmethod
    def initial(cls) -> "BoardState":
        """Return a ``BoardState`` representing the standard chess starting
        position."""
        back_rank_white = list("RNBQKBNR")
        back_rank_black = list("rnbqkbnr")
        pawns_white = ["P"] * 8
        pawns_black = ["p"] * 8
        empty_row = [EMPTY_SQUARE] * 8
        squares = (
            back_rank_black
            + pawns_black
            + empty_row
            + empty_row
            + empty_row
            + empty_row
            + pawns_white
            + back_rank_white
        )
        return cls(squares=squares)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(self, square: str) -> str:
        """Return the piece code at *square* (e.g. ``"E4"``)."""
        from .protocol import SQUARE_INDEX

        idx = SQUARE_INDEX.get(square)
        if idx is None:
            raise KeyError(f"Unknown square {square!r}")
        return self.squares[idx]

    def is_empty(self, square: str) -> bool:
        """Return ``True`` when *square* is unoccupied."""
        return self.get(square) == EMPTY_SQUARE

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BoardState):
            return NotImplemented
        return self.squares == other.squares

    def __repr__(self) -> str:
        rows = []
        for rank_idx in range(8):
            rank = SQUARE_NAMES[rank_idx * 8 : rank_idx * 8 + 8]
            row_pieces = "".join(self.squares[rank_idx * 8 : rank_idx * 8 + 8])
            rows.append(f"  {rank[0][1]} {row_pieces}")
        return "BoardState(\n" + "\n".join(rows) + "\n    ABCDEFGH\n)"


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


@dataclass
class Move:
    """A single piece move detected from two successive board states.

    Attributes
    ----------
    from_square:
        The square the piece moved *from* (e.g. ``"E2"``).
    to_square:
        The square the piece moved *to* (e.g. ``"E4"``).
    piece:
        The piece code that moved (e.g. ``"P"``).
    captured:
        The piece code that was captured, or ``None``.
    is_castling:
        ``True`` when this move is a king castling move (the rook move is
        represented by the companion ``rook_move`` attribute).
    rook_move:
        For castling moves, the companion rook ``Move``; otherwise ``None``.
    is_en_passant:
        ``True`` when this is an en-passant pawn capture.
    promotion:
        The piece code the pawn promoted to, or ``None``.
    """

    from_square: str
    to_square: str
    piece: str
    captured: Optional[str] = None
    is_castling: bool = False
    rook_move: Optional["Move"] = None
    is_en_passant: bool = False
    promotion: Optional[str] = None

    def __str__(self) -> str:
        move_str = f"{self.from_square}-{self.to_square}"
        if self.promotion:
            move_str += f"={self.promotion.upper()}"
        if self.is_castling:
            # Determine O-O vs O-O-O from destination file
            move_str = "O-O-O" if self.to_square[0] in "CD" else "O-O"
        return move_str

    @property
    def piece_name(self) -> str:
        """Human-readable piece name."""
        return PIECE_NAMES.get(self.piece, self.piece)


# ---------------------------------------------------------------------------
# MoveDetector
# ---------------------------------------------------------------------------


class MoveDetector:
    """Detect chess moves from successive :class:`BoardState` snapshots.

    Usage::

        detector = MoveDetector()
        # … update board state on every scan …
        moves = detector.update(new_state)
        for move in moves:
            print(move)
    """

    def __init__(self, initial_state: Optional[BoardState] = None) -> None:
        self._previous: Optional[BoardState] = initial_state

    @property
    def previous_state(self) -> Optional[BoardState]:
        """The last-recorded :class:`BoardState`, or ``None``."""
        return self._previous

    def update(self, new_state: BoardState) -> list[Move]:
        """Compare *new_state* against the stored previous state.

        Parameters
        ----------
        new_state:
            The latest snapshot received from the board.

        Returns
        -------
        list[Move]
            The move(s) detected between the previous and new states, or an
            empty list when nothing changed or no previous state is known.
        """
        if self._previous is None or new_state == self._previous:
            self._previous = new_state
            return []

        moves = self._detect_moves(self._previous, new_state)
        self._previous = new_state
        return moves

    def reset(self, state: Optional[BoardState] = None) -> None:
        """Clear internal state, optionally setting a new reference *state*."""
        self._previous = state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_moves(prev: BoardState, curr: BoardState) -> list[Move]:
        """Return the moves that transform *prev* into *curr*."""
        # Find changed squares
        lifted: list[tuple[int, str]] = []  # (index, old_piece)
        placed: list[tuple[int, str]] = []  # (index, new_piece)
        for i, (old, new) in enumerate(zip(prev.squares, curr.squares)):
            if old == new:
                continue
            if old != EMPTY_SQUARE and new == EMPTY_SQUARE:
                lifted.append((i, old))
            elif old == EMPTY_SQUARE and new != EMPTY_SQUARE:
                placed.append((i, new))
            elif old != EMPTY_SQUARE and new != EMPTY_SQUARE:
                # Capture destination: moving piece replaced opponent's piece
                placed.append((i, new))

        if not lifted and not placed:
            return []

        # ------------------------------------------------------------------
        # Castling: king + rook both move simultaneously
        # ------------------------------------------------------------------
        if len(lifted) == 2 and len(placed) == 2:
            castling = _try_castling(lifted, placed, prev, curr)
            if castling:
                return castling

        # ------------------------------------------------------------------
        # En passant: moving pawn + captured pawn both vacate; 1 placed
        # ------------------------------------------------------------------
        if len(lifted) == 2 and len(placed) == 1:
            ep = _try_en_passant(lifted, placed)
            if ep:
                return ep

        # ------------------------------------------------------------------
        # Standard move or capture (1 piece lifted, 1 placed)
        # ------------------------------------------------------------------
        if len(lifted) == 1 and len(placed) == 1:
            from_idx, old_piece = lifted[0]
            to_idx, new_piece = placed[0]
            from_sq = SQUARE_NAMES[from_idx]
            to_sq = SQUARE_NAMES[to_idx]
            captured_piece: Optional[str] = None
            is_en_passant = False
            promotion: Optional[str] = None

            # Pawn promotion: piece placed is different from piece lifted
            if old_piece.upper() == "P" and new_piece.upper() != "P":
                # Both must be on the same colour's back rank
                to_rank = to_sq[1]
                if (old_piece == "P" and to_rank == "8") or (
                    old_piece == "p" and to_rank == "1"
                ):
                    promotion = new_piece

            # En-passant: pawn moves diagonally but destination was empty
            if old_piece.upper() == "P" and from_sq[0] != to_sq[0]:
                ep_candidate = f"{to_sq[0]}{from_sq[1]}"
                captured_on_board = prev.get(ep_candidate)
                if captured_on_board in BLACK_PIECES | WHITE_PIECES:
                    # Check that that square is now empty
                    if curr.get(ep_candidate) == EMPTY_SQUARE:
                        is_en_passant = True
                        captured_piece = captured_on_board

            # Ordinary capture: the square contained an opponent piece
            if not is_en_passant:
                prev_piece_at_dest = prev.squares[to_idx]
                if prev_piece_at_dest != EMPTY_SQUARE:
                    captured_piece = prev_piece_at_dest

            actual_piece = old_piece if promotion is None else old_piece
            return [
                Move(
                    from_square=from_sq,
                    to_square=to_sq,
                    piece=actual_piece,
                    captured=captured_piece,
                    is_en_passant=is_en_passant,
                    promotion=promotion,
                )
            ]

        # ------------------------------------------------------------------
        # Ambiguous / partial pick-up: return raw diff as best effort
        # ------------------------------------------------------------------
        return _fallback_moves(lifted, placed, prev)


# ---------------------------------------------------------------------------
# Castling helper
# ---------------------------------------------------------------------------


def _try_castling(
    lifted: list[tuple[int, str]],
    placed: list[tuple[int, str]],
    prev: BoardState,
    curr: BoardState,
) -> list[Move]:
    """Return a list with one castling king-Move (and rook companion) if the
    four changed squares represent a valid castling move; otherwise ``[]``."""
    lifted_pieces = {SQUARE_NAMES[i]: p for i, p in lifted}
    placed_pieces = {SQUARE_NAMES[i]: p for i, p in placed}

    # Identify which colour is castling
    for king_code, rook_code in (("K", "R"), ("k", "r")):
        king_from = next(
            (sq for sq, p in lifted_pieces.items() if p == king_code), None
        )
        rook_from = next(
            (sq for sq, p in lifted_pieces.items() if p == rook_code), None
        )
        king_to = next(
            (sq for sq, p in placed_pieces.items() if p == king_code), None
        )
        rook_to = next(
            (sq for sq, p in placed_pieces.items() if p == rook_code), None
        )
        if not all([king_from, rook_from, king_to, rook_to]):
            continue
        # Validate expected squares
        expected_rank = "1" if king_code == "K" else "8"
        if not all(sq[1] == expected_rank for sq in [king_from, rook_from, king_to, rook_to]):  # type: ignore[index]
            continue
        rook_move = Move(from_square=rook_from, to_square=rook_to, piece=rook_code)  # type: ignore[arg-type]
        king_move = Move(
            from_square=king_from,  # type: ignore[arg-type]
            to_square=king_to,  # type: ignore[arg-type]
            piece=king_code,
            is_castling=True,
            rook_move=rook_move,
        )
        return [king_move]
    return []


# ---------------------------------------------------------------------------
# En passant helper
# ---------------------------------------------------------------------------


def _try_en_passant(
    lifted: list[tuple[int, str]],
    placed: list[tuple[int, str]],
) -> list[Move]:
    """Return an en-passant Move when 2 lifted + 1 placed matches the pattern.

    Pattern: a pawn moves diagonally (lifting from file F1) to a square on
    file F2, while an opponent's pawn on the same rank as the source but on
    file F2 is also lifted.
    """
    to_idx, to_piece = placed[0]
    to_sq = SQUARE_NAMES[to_idx]

    for i in range(2):
        from_idx, from_piece = lifted[i]
        other_idx, other_piece = lifted[1 - i]
        from_sq = SQUARE_NAMES[from_idx]
        other_sq = SQUARE_NAMES[other_idx]

        if from_piece.upper() != "P":
            continue
        # Moving pawn must move diagonally (different file)
        if from_sq[0] == to_sq[0]:
            continue
        # The other lifted piece must be an opponent's pawn
        if other_piece.upper() != "P":
            continue
        # Opposite colours
        if from_piece.isupper() == other_piece.isupper():
            continue
        # The captured pawn must have been on the destination file, same rank as source
        if other_sq[0] != to_sq[0]:
            continue
        if other_sq[1] != from_sq[1]:
            continue

        return [
            Move(
                from_square=from_sq,
                to_square=to_sq,
                piece=from_piece,
                captured=other_piece,
                is_en_passant=True,
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


def _fallback_moves(
    lifted: list[tuple[int, str]],
    placed: list[tuple[int, str]],
    prev: BoardState,
) -> list[Move]:
    """Return best-effort moves when the change pattern is ambiguous."""
    moves: list[Move] = []
    for i, piece in lifted:
        from_sq = SQUARE_NAMES[i]
        # Match with a placed square of the same piece type if possible
        match = next(
            ((j, p) for j, p in placed if p == piece or p.upper() == piece.upper()),
            None,
        )
        if match:
            to_idx, to_piece = match
            placed.remove(match)
            moves.append(
                Move(
                    from_square=from_sq,
                    to_square=SQUARE_NAMES[to_idx],
                    piece=piece,
                )
            )
    return moves
