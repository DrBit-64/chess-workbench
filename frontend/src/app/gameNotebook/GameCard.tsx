import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { GameResults } from './catalogApi';
import { gameTimeControl } from './gameTimeControl';
import { NoteExcerpt } from './NoteExcerpt';
import { PositionThumbnail } from './PositionThumbnail';

const startDateTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

type CatalogGame = GameResults['items'][number];

function GameDate({ game }: { game: CatalogGame }) {
  if (!game.started_at && /^\d{4}/.test(game.date)) {
    return <>{game.date.replace(/(?:[.-]\?\?)+$/, '')}</>;
  }
  const imported = !game.started_at;
  const timestamp = game.started_at ?? game.created_at;
  const local = startDateTime.format(new Date(timestamp));
  const label = imported ? '导入时间（本地时间）' : '对局开始时间（本地时间）';
  return (
    <time dateTime={timestamp} title={label} aria-label={`${label} ${local}`}>
      {imported ? '导入于 ' : ''}
      {local}
    </time>
  );
}

function Player({
  name,
  rating,
  side,
}: {
  name: string;
  rating: number | null;
  side: 'white' | 'black';
}) {
  return (
    <div className="nb-game-player">
      <span className={`nb-player-disc ${side}`} aria-hidden="true" />
      <span>
        <span className="sr-only">{side === 'white' ? '白方' : '黑方'} </span>
        <strong>{name}</strong>{' '}
        <span className="nb-player-rating" title="对局时的等级分">
          ({rating ?? '—'})
        </span>
      </span>
    </div>
  );
}

export function GameCard({
  game,
  returnState,
  onOpen,
  children,
}: {
  game: CatalogGame;
  returnState: { notebookBack: string };
  onOpen: () => void;
  children: ReactNode;
}) {
  const href = '/games/' + game.id;
  const result = game.result === '1/2-1/2' ? '½–½' : game.result;
  const clock = gameTimeControl(game.time_control);
  const source =
    game.platform === 'lichess'
      ? 'Lichess'
      : game.platform === 'chess.com'
        ? 'Chess.com'
        : game.platform;
  return (
    <li className="nb-game-card">
      <Link
        to={href}
        state={returnState}
        onClick={onOpen}
        className="nb-game-card-main"
      >
        <div
          className="nb-game-diagram"
          data-fen={game.final_fen}
          role="img"
          aria-label="实战主线的最终局面"
        >
          <PositionThumbnail fen={game.final_fen} />
        </div>
        <div className="nb-game-players">
          <Player side="white" name={game.white} rating={game.white_rating} />
          <Player side="black" name={game.black} rating={game.black_rating} />
          <p className="nb-game-result">
            <span>
              <span className="sr-only">对局结果 </span>
              {result}
            </span>
            <span className="nb-game-clock">时限 {clock}</span>
          </p>
        </div>
      </Link>
      <div className="nb-game-opening">
        {game.opening_eco && (
          <span className="nb-opening-eco">{game.opening_eco} </span>
        )}
        <span>{game.opening_name ?? '未识别开局'}</span>
      </div>
      <p className="nb-meta">
        <GameDate game={game} />
        {source && ` · ${source}`}
      </p>
      {game.summary && <NoteExcerpt text={game.summary} previewLength={64} />}
      <div className="nb-actions nb-card-actions">
        <Link to={href} className="nb-btn" state={returnState} onClick={onOpen}>
          打开棋谱
        </Link>
        {children}
      </div>
    </li>
  );
}
