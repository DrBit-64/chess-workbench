import { DEFAULT_POSITION } from 'chess.js';
import type { ReviewNode } from './reviewTypes';

type ClockNode = Pick<
  ReviewNode,
  'id' | 'is_mainline' | 'ply' | 'fen' | 'san' | 'comment'
>;
type ClockPair = { white?: string; black?: string };

function displayTime(
  hours: number,
  minutes: number,
  seconds: number,
  fraction = '',
) {
  const mm = String(minutes).padStart(2, '0');
  const ss = String(seconds).padStart(2, '0');
  return (
    (hours ? hours + ':' : '') +
    mm +
    ':' +
    ss +
    fraction.replace(/0+$/, '').replace(/\.$/, '')
  );
}

function annotatedClock(comment: string) {
  const match = /\[%clk\s+(\d{1,6}):([0-5]\d):([0-5]\d)(\.\d+)?\s*\]/i.exec(
    comment,
  );
  return match
    ? displayTime(
        Number(match[1]),
        Number(match[2]),
        Number(match[3]),
        match[4],
      )
    : undefined;
}

function startingClock(timeControl: string | undefined) {
  const firstStage = timeControl?.split(':')[0].trim();
  // PGN seconds, seconds+increment or moves/seconds; the initial clock excludes increment.
  const match = /^(?:\d+\/)?(\d{1,9})(?:\+\d+)?$/.exec(firstStage ?? '');
  if (!match) return undefined;
  const seconds = Number(match[1]);
  return displayTime(
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  );
}

/** A clock annotation is the mover's recorded time after the move, irrespective of board orientation. */
export function mainlineClocks(nodes: ClockNode[], timeControl?: string) {
  const clocks = new Map<string, ClockPair>();
  let pair: ClockPair = {};
  let hasReadings = false;
  for (const node of nodes
    .filter((n) => n.is_mainline)
    .sort((a, b) => a.ply - b.ply)) {
    if (!node.san) {
      const initial =
        node.fen === DEFAULT_POSITION ? startingClock(timeControl) : undefined;
      pair = { white: initial, black: initial };
    } else {
      const after = annotatedClock(node.comment);
      if (after !== undefined) hasReadings = true;
      const mover = node.fen.split(' ')[1] === 'w' ? 'black' : 'white';
      // A missing stamp on this move invalidates this player's older reading.
      pair = { ...pair, [mover]: after };
    }
    clocks.set(node.id, pair);
  }
  return hasReadings ? clocks : undefined;
}
