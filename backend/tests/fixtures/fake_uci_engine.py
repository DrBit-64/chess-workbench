#!/usr/bin/env python3
"""Deterministic UCI fixture used only by Stage 6 tests."""

import os
import sys
import time
from pathlib import Path

mode = os.environ.get("FAKE_UCI_MODE", "normal")
multipv = 1
position = "startpos"
if pid_file := os.environ.get("FAKE_UCI_PID_FILE"):
    Path(pid_file).write_text(str(os.getpid()))


def send(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


for raw in sys.stdin:
    command = raw.strip()
    if command == "uci":
        if mode == "handshake-timeout":
            time.sleep(10)
            continue
        send("id name FakeFish 1.2")
        send("id author ChessWorkbench")
        send("option name Threads type spin default 1 min 1 max 32")
        send("option name Hash type spin default 16 min 1 max 4096")
        send("option name Ponder type check default false")
        send("option name MultiPV type spin default 1 min 1 max 5")
        send("option name UCI_LimitStrength type check default false")
        send("option name UCI_Elo type spin default 1500 min 1320 max 2850")
        send("uciok")
    elif command.startswith("setoption name MultiPV value "):
        multipv = int(command.rsplit(" ", 1)[-1])
    elif command == "isready":
        send("readyok")
    elif command.startswith("position "):
        position = command
    elif command.startswith("go"):
        if mode == "timeout":
            time.sleep(10)
            continue
        if mode == "crash":
            raise SystemExit(17)
        if mode == "malformed":
            send("info depth 8 score cp 20")
            send("bestmove 0000")
            continue
        if " b " in position or "moves e2e4" in position:
            send("info depth 8 seldepth 10 multipv 1 score cp 5 nodes 80 pv e7e5 g1f3")
            send("bestmove e7e5")
            continue
        variations = [
            (34, "e2e4 e7e5 g1f3"),
            (27, "d2d4 d7d5 c2c4"),
            (18, "g1f3 d7d5 d2d4"),
            (12, "c2c4 e7e5 b1c3"),
            (7, "b2b3 d7d5 c1b2"),
        ]
        for index, (score, pv) in enumerate(variations[:multipv], 1):
            send(
                f"info depth 12 seldepth 16 multipv {index} score cp {score} "
                f"nodes {1000 + index} pv {pv}"
            )
        send("bestmove e2e4 ponder e7e5")
    elif command == "stop":
        send("bestmove e2e4")
    elif command == "quit":
        raise SystemExit(0)
