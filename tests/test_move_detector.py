"""
Unit tests for millennium.move_detector (BoardState, Move, MoveDetector)
"""

import pytest
from millennium.move_detector import BoardState, Move, MoveDetector
from millennium.protocol import EMPTY_SQUARE


# ---------------------------------------------------------------------------
# BoardState
# ---------------------------------------------------------------------------


def _empty_board() -> BoardState:
    return BoardState(squares=[EMPTY_SQUARE] * 64)


def _initial_board() -> BoardState:
    return BoardState.initial()


def test_boardstate_initial_has_64_squares():
    b = _initial_board()
    assert len(b.squares) == 64


def test_boardstate_initial_correct_pieces():
    b = _initial_board()
    # Black back rank (row 0 = rank 8)
    assert b.squares[0] == "r"   # A8
    assert b.squares[4] == "k"   # E8
    # White back rank (row 7 = rank 1)
    assert b.squares[56] == "R"  # A1
    assert b.squares[60] == "K"  # E1
    # Pawns
    assert b.squares[8] == "p"   # A7
    assert b.squares[48] == "P"  # A2


def test_boardstate_get_square():
    b = _initial_board()
    assert b.get("E1") == "K"
    assert b.get("E8") == "k"
    assert b.get("D4") == EMPTY_SQUARE


def test_boardstate_is_empty():
    b = _initial_board()
    assert b.is_empty("D4")
    assert not b.is_empty("E1")


def test_boardstate_invalid_square():
    b = _empty_board()
    with pytest.raises(KeyError):
        b.get("Z9")


def test_boardstate_invalid_length():
    with pytest.raises(ValueError):
        BoardState(squares=[EMPTY_SQUARE] * 63)


def test_boardstate_invalid_piece_code():
    with pytest.raises(ValueError):
        BoardState(squares=["X"] + [EMPTY_SQUARE] * 63)


def test_boardstate_equality():
    assert _empty_board() == _empty_board()
    assert _initial_board() == _initial_board()
    assert _empty_board() != _initial_board()


def test_boardstate_from_piece_codes():
    codes = [EMPTY_SQUARE] * 64
    b = BoardState.from_piece_codes(codes)
    assert b == _empty_board()


def test_boardstate_repr():
    b = _empty_board()
    r = repr(b)
    assert "BoardState" in r
    assert "ABCDEFGH" in r


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


def test_move_str_simple():
    m = Move(from_square="E2", to_square="E4", piece="P")
    assert str(m) == "E2-E4"


def test_move_str_with_promotion():
    m = Move(from_square="E7", to_square="E8", piece="P", promotion="Q")
    assert str(m) == "E7-E8=Q"


def test_move_str_kingside_castling():
    m = Move(from_square="E1", to_square="G1", piece="K", is_castling=True)
    assert str(m) == "O-O"


def test_move_str_queenside_castling():
    m = Move(from_square="E1", to_square="C1", piece="K", is_castling=True)
    assert str(m) == "O-O-O"


def test_move_piece_name():
    m = Move(from_square="E2", to_square="E4", piece="P")
    assert m.piece_name == "white pawn"


# ---------------------------------------------------------------------------
# MoveDetector – no previous state
# ---------------------------------------------------------------------------


def test_move_detector_no_previous():
    detector = MoveDetector()
    b = _initial_board()
    moves = detector.update(b)
    assert moves == []
    assert detector.previous_state == b


def test_move_detector_no_change():
    b = _initial_board()
    detector = MoveDetector(initial_state=b)
    moves = detector.update(b)
    assert moves == []


# ---------------------------------------------------------------------------
# MoveDetector – simple pawn move
# ---------------------------------------------------------------------------


def _apply_move(state: BoardState, from_sq: str, to_sq: str) -> BoardState:
    """Return a new BoardState with the piece at *from_sq* moved to *to_sq*."""
    from millennium.protocol import SQUARE_INDEX

    squares = list(state.squares)
    f_idx = SQUARE_INDEX[from_sq]
    t_idx = SQUARE_INDEX[to_sq]
    squares[t_idx] = squares[f_idx]
    squares[f_idx] = EMPTY_SQUARE
    return BoardState(squares=squares)


def test_detect_pawn_push():
    prev = _initial_board()
    curr = _apply_move(prev, "E2", "E4")
    detector = MoveDetector(initial_state=prev)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.from_square == "E2"
    assert m.to_square == "E4"
    assert m.piece == "P"
    assert m.captured is None


# ---------------------------------------------------------------------------
# MoveDetector – capture
# ---------------------------------------------------------------------------


def test_detect_capture():
    from millennium.protocol import SQUARE_INDEX

    prev = _initial_board()
    # Manually set up a simple capture position
    squares = list(prev.squares)
    # Put a black pawn at D4 (empty square)
    squares[SQUARE_INDEX["D4"]] = "p"
    prev2 = BoardState(squares=squares)

    # White pawn on E3 captures to D4
    squares2 = list(squares)
    squares2[SQUARE_INDEX["E3"]] = "P"
    prev3 = BoardState(squares=squares2)

    curr = _apply_move(prev3, "E3", "D4")
    detector = MoveDetector(initial_state=prev3)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.from_square == "E3"
    assert m.to_square == "D4"
    assert m.piece == "P"
    assert m.captured == "p"


# ---------------------------------------------------------------------------
# MoveDetector – castling
# ---------------------------------------------------------------------------


def test_detect_kingside_castling():
    from millennium.protocol import SQUARE_INDEX

    # Set up a position where white can castle kingside
    squares = [EMPTY_SQUARE] * 64
    squares[SQUARE_INDEX["E1"]] = "K"
    squares[SQUARE_INDEX["H1"]] = "R"
    prev = BoardState(squares=squares)

    # After castling: K→G1, R→F1
    squares2 = list(squares)
    squares2[SQUARE_INDEX["E1"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["H1"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["G1"]] = "K"
    squares2[SQUARE_INDEX["F1"]] = "R"
    curr = BoardState(squares=squares2)

    detector = MoveDetector(initial_state=prev)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.is_castling
    assert m.piece == "K"
    assert m.from_square == "E1"
    assert m.to_square == "G1"
    assert m.rook_move is not None
    assert m.rook_move.from_square == "H1"
    assert m.rook_move.to_square == "F1"


def test_detect_queenside_castling():
    from millennium.protocol import SQUARE_INDEX

    squares = [EMPTY_SQUARE] * 64
    squares[SQUARE_INDEX["E1"]] = "K"
    squares[SQUARE_INDEX["A1"]] = "R"
    prev = BoardState(squares=squares)

    squares2 = list(squares)
    squares2[SQUARE_INDEX["E1"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["A1"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["C1"]] = "K"
    squares2[SQUARE_INDEX["D1"]] = "R"
    curr = BoardState(squares=squares2)

    detector = MoveDetector(initial_state=prev)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.is_castling
    assert str(m) == "O-O-O"


# ---------------------------------------------------------------------------
# MoveDetector – en passant
# ---------------------------------------------------------------------------


def test_detect_en_passant():
    from millennium.protocol import SQUARE_INDEX

    # White pawn on E5, black pawn just moved to D5
    squares = [EMPTY_SQUARE] * 64
    squares[SQUARE_INDEX["E5"]] = "P"
    squares[SQUARE_INDEX["D5"]] = "p"
    prev = BoardState(squares=squares)

    # En passant: E5 → D6, black pawn on D5 disappears
    squares2 = list(squares)
    squares2[SQUARE_INDEX["E5"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["D5"]] = EMPTY_SQUARE  # captured pawn removed
    squares2[SQUARE_INDEX["D6"]] = "P"
    curr = BoardState(squares=squares2)

    detector = MoveDetector(initial_state=prev)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.from_square == "E5"
    assert m.to_square == "D6"
    assert m.is_en_passant
    assert m.captured == "p"


# ---------------------------------------------------------------------------
# MoveDetector – promotion
# ---------------------------------------------------------------------------


def test_detect_promotion():
    from millennium.protocol import SQUARE_INDEX

    squares = [EMPTY_SQUARE] * 64
    squares[SQUARE_INDEX["E7"]] = "P"
    prev = BoardState(squares=squares)

    squares2 = list(squares)
    squares2[SQUARE_INDEX["E7"]] = EMPTY_SQUARE
    squares2[SQUARE_INDEX["E8"]] = "Q"  # promoted to queen
    curr = BoardState(squares=squares2)

    detector = MoveDetector(initial_state=prev)
    moves = detector.update(curr)
    assert len(moves) == 1
    m = moves[0]
    assert m.from_square == "E7"
    assert m.to_square == "E8"
    assert m.promotion == "Q"
    assert str(m) == "E7-E8=Q"


# ---------------------------------------------------------------------------
# MoveDetector – reset
# ---------------------------------------------------------------------------


def test_move_detector_reset():
    b = _initial_board()
    detector = MoveDetector(initial_state=b)
    detector.reset()
    assert detector.previous_state is None
    moves = detector.update(b)
    assert moves == []  # first update after reset sets baseline
