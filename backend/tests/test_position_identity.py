from __future__ import annotations

import chess
import pytest
from chess_workbench.domain import (
    POSITION_KEY_PREFIX,
    POSITION_KEY_VERSION,
    PositionError,
    PositionErrorCode,
    PositionState,
    apply_uci_move,
    parse_position,
)
from hypothesis import given, note, seed, settings
from hypothesis import strategies as st

START_FEN = chess.STARTING_FEN
AFTER_E4_WITH_RAW_EP = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
LEGAL_EP_FEN = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
PINNED_EP_FEN = "k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
PROPERTY_TEST_SEED = 20_260_806


def test_starting_position_exposes_versioned_identity_and_derived_fields() -> None:
    state = parse_position(START_FEN)

    assert state.position_key == (
        "standard:v1:rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
    )
    assert state.full_fen == START_FEN
    assert state.canonical_fen == START_FEN
    assert state.piece_placement == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    assert state.side_to_move == "w"
    assert state.castling_rights == "KQkq"
    assert state.en_passant == "-"
    assert state.material_signature == "v1:w:K1Q1R2B2N2P8|b:K1Q1R2B2N2P8"
    assert POSITION_KEY_VERSION == "v1"
    assert state.position_key.startswith(POSITION_KEY_PREFIX)


def test_clocks_do_not_change_identity_but_remain_in_full_fen() -> None:
    early = PositionState.from_fen("8/8/8/8/8/4k3/8/4K3 w - - 0 1")
    late = PositionState.from_fen("8/8/8/8/8/4k3/8/4K3 w - - 99 73")

    assert early.position_key == late.position_key
    assert early.canonical_fen == late.canonical_fen == "8/8/8/8/8/4k3/8/4K3 w - - 0 1"
    assert early.full_fen.endswith(" 0 1")
    assert late.full_fen.endswith(" 99 73")


def test_side_to_move_and_castling_rights_are_part_of_identity() -> None:
    with_rights = PositionState("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    without_rights = PositionState("r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1")
    black_to_move = PositionState("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1")

    assert with_rights.position_key != without_rights.position_key
    assert with_rights.position_key != black_to_move.position_key


def test_irrelevant_raw_en_passant_is_preserved_but_not_part_of_identity() -> None:
    with_raw_target = PositionState(AFTER_E4_WITH_RAW_EP)
    without_target = PositionState(AFTER_E4_WITH_RAW_EP.replace(" e3 ", " - "))

    assert with_raw_target.full_fen == AFTER_E4_WITH_RAW_EP
    assert with_raw_target.en_passant == "-"
    assert with_raw_target.position_key == without_target.position_key
    assert with_raw_target.canonical_fen == without_target.canonical_fen


def test_only_a_legal_en_passant_capture_changes_identity() -> None:
    legal_target = PositionState(LEGAL_EP_FEN)
    no_target = PositionState(LEGAL_EP_FEN.replace(" d6 ", " - "))

    assert legal_target.en_passant == "d6"
    assert legal_target.position_key != no_target.position_key


def test_pseudo_legal_but_pinned_en_passant_is_not_part_of_identity() -> None:
    pinned_target = PositionState(PINNED_EP_FEN)
    no_target = PositionState(PINNED_EP_FEN.replace(" d6 ", " - "))

    assert pinned_target.full_fen == PINNED_EP_FEN
    assert pinned_target.en_passant == "-"
    assert pinned_target.position_key == no_target.position_key


@pytest.mark.parametrize(
    ("fen", "expected_code"),
    [
        ("not a fen", PositionErrorCode.INVALID_FEN),
        ("8/8/8/8/8/8/8/8 w - -", PositionErrorCode.INVALID_FEN),
        ("8/8/8/8/8/8/8/x7 w - - 0 1", PositionErrorCode.INVALID_FEN),
        ("r3k2r/8/8/8/8/8/8/R3K2R w HAha - 0 1", PositionErrorCode.INVALID_FEN),
        ("4k3/8/8/8/8/8/Q~7/4K3 w - - 0 1", PositionErrorCode.INVALID_FEN),
        ("8/8/8/8/8/8/8/8 w - - 0 1", PositionErrorCode.ILLEGAL_POSITION),
        ("8/8/8/8/8/8/4k3/4K3 w - - 0 1", PositionErrorCode.ILLEGAL_POSITION),
        ("4k3/8/8/8/8/8/8/4K3 w K - 0 1", PositionErrorCode.ILLEGAL_POSITION),
    ],
)
def test_invalid_fen_has_stable_domain_error(fen: str, expected_code: PositionErrorCode) -> None:
    with pytest.raises(PositionError) as error_info:
        PositionState.from_fen(fen)

    assert error_info.value.code is expected_code
    assert str(error_info.value) == error_info.value.message
    assert str(error_info.value) in {
        "FEN must contain six valid standard-chess fields.",
        "FEN must describe a structurally legal standard-chess position.",
    }


def test_non_string_fen_has_stable_domain_error() -> None:
    with pytest.raises(PositionError) as error_info:
        PositionState.from_fen(None)  # type: ignore[arg-type]

    assert error_info.value.code is PositionErrorCode.INVALID_FEN


@pytest.mark.parametrize("uci", ["", "E2E4", "e2-e4", "e7e8k", "e2e2"])
def test_invalid_uci_has_stable_domain_error(uci: str) -> None:
    with pytest.raises(PositionError) as error_info:
        apply_uci_move(PositionState(START_FEN), uci)

    assert error_info.value.code is PositionErrorCode.INVALID_UCI
    assert str(error_info.value) == "Move must use standard UCI notation."


@pytest.mark.parametrize("uci", ["e2e5", "e7e5", "e1g1"])
def test_well_formed_but_illegal_move_has_stable_domain_error(uci: str) -> None:
    with pytest.raises(PositionError) as error_info:
        PositionState(START_FEN).apply_uci(uci)

    assert error_info.value.code is PositionErrorCode.ILLEGAL_MOVE
    assert str(error_info.value) == "Move is not legal in the supplied position."


def test_a_move_must_resolve_check_before_it_is_persisted() -> None:
    checked = PositionState("4k3/8/8/8/8/8/4r3/R3K3 w Q - 0 1")

    with pytest.raises(PositionError) as error_info:
        checked.apply_uci("a1a2")

    result = checked.apply_uci("e1e2")
    assert error_info.value.code is PositionErrorCode.ILLEGAL_MOVE
    assert result.san == "Kxe2"
    assert result.after.full_fen == "4k3/8/8/8/8/8/4K3/R7 b - - 0 1"


@pytest.mark.parametrize(
    ("fen", "uci", "expected_san", "expected_after_fen"),
    [
        (START_FEN, "e2e4", "e4", AFTER_E4_WITH_RAW_EP),
        (
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            "e1g1",
            "O-O",
            "r3k2r/8/8/8/8/8/8/R4RK1 b kq - 1 1",
        ),
        (
            LEGAL_EP_FEN,
            "e5d6",
            "exd6",
            "4k3/8/3P4/8/8/8/8/4K3 b - - 0 2",
        ),
        (
            "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
            "a7a8q",
            "a8=Q+",
            "Q3k3/8/8/8/8/8/8/4K3 b - - 0 1",
        ),
    ],
)
def test_legal_uci_returns_san_and_authoritative_target_state(
    fen: str,
    uci: str,
    expected_san: str,
    expected_after_fen: str,
) -> None:
    before = PositionState(fen)

    result = before.apply_uci(uci)

    assert result.before is before
    assert result.uci == uci
    assert result.san == expected_san
    assert result.after.full_fen == expected_after_fen


def test_transposed_move_orders_share_graph_identity_but_keep_full_state() -> None:
    def play(moves: tuple[str, ...]) -> PositionState:
        state = PositionState(START_FEN)
        for uci in moves:
            state = state.apply_uci(uci).after
        return state

    knight_first = play(("g1f3", "g8f6", "g2g3"))
    pawn_first = play(("g2g3", "g8f6", "g1f3"))

    assert knight_first.position_key == pawn_first.position_key
    assert knight_first.canonical_fen == pawn_first.canonical_fen
    assert knight_first.full_fen != pawn_first.full_fen


@seed(PROPERTY_TEST_SEED)
@settings(max_examples=100, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=255), min_size=1, max_size=80))
def test_property_every_generated_legal_move_matches_python_chess(
    decisions: list[int],
) -> None:
    note(f"seed={PROPERTY_TEST_SEED}; decisions={decisions!r}")
    board = chess.Board()
    for decision in decisions[:-1]:
        legal_moves = sorted(board.legal_moves, key=lambda candidate: candidate.uci())
        if not legal_moves:
            board.reset()
            break
        board.push(legal_moves[decision % len(legal_moves)])

    legal_moves = sorted(board.legal_moves, key=lambda candidate: candidate.uci())
    move = legal_moves[decisions[-1] % len(legal_moves)]
    expected_san = board.san(move)
    before = PositionState(board.fen(en_passant="fen"))
    expected_board = board.copy()
    expected_board.push(move)

    result = apply_uci_move(before, move.uci())

    assert result.san == expected_san
    assert result.after.full_fen == expected_board.fen(en_passant="fen")
    assert result.after == PositionState(expected_board.fen(en_passant="fen"))


@seed(PROPERTY_TEST_SEED)
@settings(max_examples=50, deadline=None)
@given(
    halfmove_clock=st.integers(min_value=0, max_value=150),
    fullmove_number=st.integers(min_value=1, max_value=500),
)
def test_property_clock_values_never_change_graph_identity(
    halfmove_clock: int, fullmove_number: int
) -> None:
    note(f"seed={PROPERTY_TEST_SEED}; halfmove={halfmove_clock}; fullmove={fullmove_number}")
    identity = "4k3/8/8/3pP3/8/8/8/4K3 w - d6"
    baseline = PositionState(f"{identity} 0 1")
    changed = PositionState(f"{identity} {halfmove_clock} {fullmove_number}")

    assert changed.position_key == baseline.position_key
    assert changed.canonical_fen == baseline.canonical_fen
    assert changed.full_fen.endswith(f" {halfmove_clock} {fullmove_number}")
