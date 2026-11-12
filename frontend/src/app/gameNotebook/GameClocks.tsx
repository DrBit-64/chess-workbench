import { useMemo } from 'react';
import { mainlineClocks } from './mainlineClocks';
import type { ReviewGame, ReviewNode } from './reviewTypes';
import './gameClocks.css';

export function useGameClocks(game: ReviewGame, node?: ReviewNode) {
  const timeControl =
    game.headers.TimeControl ??
    Object.entries(game.headers).find(
      ([tag]) => tag.toLowerCase() === 'timecontrol',
    )?.[1];
  const clocks = useMemo(
    () => mainlineClocks(game.nodes, timeControl),
    [game.nodes, timeControl],
  );
  if (!clocks) return undefined;
  const pair = node && clocks.get(node.id);
  const turn = node?.fen.split(' ')[1];
  const render = (side: 'white' | 'black') => {
    const label = side === 'white' ? '白方剩余时间' : '黑方剩余时间';
    const time = pair?.[side];
    return (
      <span
        className="game-player-clock"
        role="group"
        data-side={side}
        data-turn={turn === side[0]}
        hidden={!pair}
        aria-label={label}
        title={label + ' · ' + (time ?? '原谱未记录')}
      >
        <span className="game-player-clock-disc" aria-hidden="true" />
        {time ?? '—'}
      </span>
    );
  };
  return { white: render('white'), black: render('black') };
}
