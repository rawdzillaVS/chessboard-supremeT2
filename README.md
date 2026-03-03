# chessboard-supremeT2

A Python interface for communicating with a **Millennium chessboard** (ChessLink protocol) to detect and process piece moves.

## Overview

This library implements the *ChessLink* serial communications protocol used by Millennium electronic chessboards (Chess Genius Exclusive, eONE, Supreme Tournament, and compatible models). It lets you:

- **Connect** to the board over USB serial
- **Read** the current piece layout from the board
- **Detect moves** automatically by comparing successive board snapshots
- **Control LEDs** to highlight squares
- **Poll** the board in a background thread with callbacks for moves

## Requirements

- Python 3.8+
- [pyserial](https://pypi.org/project/pyserial/) ≥ 3.5

```
pip install -r requirements.txt
```

## Quick start

```python
from millennium import MillenniumBoard

def on_move(move):
    print(f"Move played: {move}")          # e.g. "E2-E4"
    print(f"Piece: {move.piece_name}")      # e.g. "white pawn"
    if move.captured:
        print(f"Captured: {move.captured}")
    if move.is_castling:
        print("Castling!")

with MillenniumBoard("/dev/ttyUSB0") as board:
    print("Firmware:", board.get_version())
    board.on_move(on_move)
    board.start_polling()
    input("Press Enter to stop…\n")
```

## Board connection

The Millennium ChessLink module appears as a CDC USB serial device:

| Platform | Typical port |
|----------|-------------|
| Linux    | `/dev/ttyUSB0` or `/dev/ttyACM0` |
| macOS    | `/dev/tty.usbserial-XXXX` |
| Windows  | `COM3` (or similar) |

Serial parameters are fixed by the protocol: **38400 baud, 7 bit, odd parity, 1 stop bit**.

## API reference

### `MillenniumBoard`

```python
board = MillenniumBoard(port, poll_interval=0.1)
board.connect()          # open serial port
board.disconnect()       # close serial port (also stops polling)

# Board commands
state   = board.get_board_state()        # → BoardState
version = board.get_version()            # → "2.1"
board.reset()                            # hardware reset (3 s delay)
board.extinguish_leds()
board.set_leds(slot_time, led_codes)     # 81-element list
board.highlight_squares(["E2", "E4"])    # turn LEDs on for those squares

# Callbacks & polling
board.on_move(callback)          # called with Move on each detected move
board.on_state_change(callback)  # called with BoardState on any change
board.start_polling()            # start background thread
board.stop_polling()             # stop background thread
```

### `BoardState`

Snapshot of all 64 squares.  Piece codes follow the protocol convention:
`K Q R B N P` (white), `k q r b n p` (black), `.` (empty).

```python
state = BoardState.initial()     # standard starting position
state.get("E1")                  # → "K"
state.is_empty("D4")             # → True
```

### `Move`

```python
move.from_square   # e.g. "E2"
move.to_square     # e.g. "E4"
move.piece         # e.g. "P"
move.piece_name    # e.g. "white pawn"
move.captured      # captured piece code, or None
move.is_castling   # True for castling moves
move.rook_move     # companion rook Move for castling, or None
move.is_en_passant # True for en-passant captures
move.promotion     # promoted piece code, or None
str(move)          # "E2-E4", "O-O", "E7-E8=Q", …
```

### `MoveDetector`

Can be used standalone to compare any two `BoardState` objects:

```python
from millennium import MoveDetector, BoardState

detector = MoveDetector(initial_state=BoardState.initial())
moves = detector.update(new_state)   # → list[Move]
```

## Running tests

```
pip install pytest
pytest
```

## Protocol reference

The ChessLink serial protocol is documented in
[magic-board.md](https://github.com/domschl/python-mchess/blob/master/mchess/magic-board.md)
(Dave Woodfield, 2017).  Key parameters:

| Parameter | Value |
|-----------|-------|
| Baud rate | 38400 |
| Data bits | 7 |
| Parity    | Odd  |
| Stop bits | 1    |
| Checksum  | XOR of all ASCII bytes, transmitted as 2 hex digits |
