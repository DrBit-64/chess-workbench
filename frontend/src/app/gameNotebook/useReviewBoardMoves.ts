import { Chess, type Move, type Square } from 'chess.js';
import { useEffect, useMemo, useState } from 'react';

import type { ReviewNode } from './reviewTypes';

export type ReviewDirection = 'previous' | 'next' | 'first' | 'last';

type Trial = { anchor: string; moves: Move[]; cursor: number };

export function useReviewBoardMoves(
  node: ReviewNode | undefined,
  children: ReadonlyMap<string, ReviewNode[]>,
  busy: boolean,
  onSelect: (node: ReviewNode) => void,
  onRecord: (node: ReviewNode, uci: string) => Promise<void>,
) {
  const [recording, setRecording] = useState(true);
  const [trialState, setTrial] = useState<Trial>();
  const [preview, setPreview] = useState<{ anchor: string; move: Move }>();
  const [selection, setSelection] = useState<{ fen: string; square: Square }>();
  const [promotion, setPromotion] = useState<{
    fen: string;
    from: Square;
    to: Square;
  }>();
  const trial = trialState?.anchor === node?.id ? trialState : undefined;
  const trialMove = trial && trial.moves[trial.cursor - 1];
  const pending = preview?.anchor === node?.id ? preview?.move : undefined;
  const displayed = pending ?? trialMove;
  const fen = displayed?.after ?? node?.fen;
  const board = useMemo(() => (fen ? new Chess(fen) : undefined), [fen]);
  const selected = selection?.fen === fen ? selection?.square : undefined;
  const enabled = Boolean(
    node && !busy && !pending && (!recording || !node.hidden),
  );

  function reset() {
    setTrial(undefined);
    setPreview(undefined);
    setSelection(undefined);
    setPromotion(undefined);
  }

  // Browser history and bookmark links can also change the selected move.
  useEffect(reset, [node?.id]);

  function setRecordingMode(value: boolean) {
    reset();
    setRecording(value);
  }

  function play(from: Square, to: Square, promotionPiece?: string): boolean {
    if (!node || !fen || !board || !enabled) return false;
    const destinations = board
      .moves({ square: from, verbose: true })
      .filter((move) => move.to === to);
    if (!destinations.length) return false;
    if (!promotionPiece && destinations.some((move) => move.promotion)) {
      setPromotion({ fen, from, to });
      return false;
    }
    const chosen = destinations.find(
      (move) => move.promotion === promotionPiece,
    );
    if (!chosen) return false;
    setSelection(undefined);
    setPromotion(undefined);
    if (!trialMove) {
      const existing = children.get(node.id)?.find((n) => n.uci === chosen.lan);
      if (existing) {
        onSelect(existing);
        return true;
      }
    }
    if (recording) {
      const next = { anchor: node.id, move: chosen };
      setPreview(next);
      void onRecord(node, chosen.lan).finally(() => {
        setPreview((current) => (current === next ? undefined : current));
      });
    } else {
      const moves = [...(trial?.moves.slice(0, trial.cursor) ?? []), chosen];
      setTrial({ anchor: node.id, moves, cursor: moves.length });
    }
    return true;
  }

  function click(square: Square) {
    if (!fen || !board || !enabled) return;
    if (board.get(square)?.color === board.turn()) {
      setSelection(square === selected ? undefined : { fen, square });
    } else if (selected) {
      play(selected, square);
    }
  }

  function step(direction: ReviewDirection) {
    if (!trial) return false;
    if (
      trial.cursor === 0 &&
      (direction === 'first' || direction === 'previous')
    ) {
      reset();
      return false;
    }
    const cursor =
      direction === 'first'
        ? 0
        : direction === 'last'
          ? trial.moves.length
          : direction === 'previous'
            ? Math.max(0, trial.cursor - 1)
            : Math.min(trial.moves.length, trial.cursor + 1);
    setSelection(undefined);
    setPromotion(undefined);
    setTrial({ ...trial, cursor });
    return true;
  }

  return {
    recording,
    setRecordingMode,
    enabled,
    fen,
    selected,
    click,
    play,
    promotion: promotion?.fen === fen ? promotion : undefined,
    cancelPromotion: () => setPromotion(undefined),
    reset,
    step,
    trial,
    pending: Boolean(pending),
    temporary: Boolean(displayed),
    lastMove: displayed?.lan ?? node?.uci,
  };
}
