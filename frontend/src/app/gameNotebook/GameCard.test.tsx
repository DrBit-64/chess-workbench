import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { GameResults } from './catalogApi';
import { GameCard } from './GameCard';
import { gameTimeControl } from './gameTimeControl';

const game: GameResults['items'][number] = {
  id: 'game-12',
  white: 'White player',
  black: 'Black player',
  white_rating: 1863,
  black_rating: 1746,
  time_control: '300+3',
  final_fen: '7k/pp6/8/8/8/8/PP6/K7 w - - 0 43',
  opening_eco: 'D37',
  opening_name: 'Queen’s Gambit Declined',
  date: '2026.11.12',
  started_at: '2026-11-12T12:30:00Z',
  result: '1/2-1/2',
  platform: 'lichess',
  source_url: null,
  archived_at: null,
  created_at: '2026-11-13T00:00:00Z',
  version: 1,
  summary: '残局复盘',
};

describe('game catalog card', () => {
  it('shows both original ratings, the recorded terminal board, the opening and time control', () => {
    render(
      <MemoryRouter>
        <ul>
          <GameCard
            game={game}
            returnState={{ notebookBack: '/games' }}
            onOpen={vi.fn()}
          >
            <button>归档</button>
          </GameCard>
        </ul>
      </MemoryRouter>,
    );
    const card = screen.getByRole('listitem');
    expect(card.textContent).toContain('白方 White player (1863)');
    expect(card.textContent).toContain('黑方 Black player (1746)');
    expect(card.textContent).toContain('时限 5+3');
    expect(card.querySelector('time')?.dateTime).toBe(game.started_at);
    expect(card.textContent).toContain('Queen’s Gambit Declined');
    expect(card.textContent).toContain('D37');
    const diagram = within(card).getByRole('img', {
      name: '实战主线的最终局面',
    });
    expect(diagram.getAttribute('data-fen')).toBe(game.final_fen);
    expect(diagram.querySelectorAll('cg-board piece')).toHaveLength(6);
    expect(diagram.querySelectorAll('piece.white.pawn')).toHaveLength(2);
    expect(diagram.querySelectorAll('piece.black.pawn')).toHaveLength(2);
    expect(
      within(card).getByRole('link', { name: '打开棋谱' }).getAttribute('href'),
    ).toBe('/games/game-12');
  });

  it('labels import fallback while retaining the actual precision of PGN dates', () => {
    const dates = ['2022.??.??', '2022.04.??', '2022.04.09', '????.??.??'];
    render(
      <MemoryRouter>
        <ul>
          {dates.map((date) => (
            <GameCard
              key={date}
              game={{ ...game, date, started_at: null }}
              returnState={{ notebookBack: '/games' }}
              onOpen={vi.fn()}
            >
              {null}
            </GameCard>
          ))}
        </ul>
      </MemoryRouter>,
    );
    const [year, month, day, missing] = screen.getAllByRole('listitem');
    for (const [card, text] of [
      [year, '2022'],
      [month, '2022.04'],
      [day, '2022.04.09'],
    ] as const) {
      expect(card.querySelector('.nb-meta')?.textContent).toBe(
        text + ' · Lichess',
      );
      expect(card.querySelector('time')).toBeNull();
    }
    const fallback = within(missing).getByTitle('导入时间（本地时间）');
    expect(fallback.getAttribute('datetime')).toBe(game.created_at);
    expect(fallback.textContent).toMatch(/^导入于 .+\d{2}:\d{2}$/);
  });

  it('handles fixed time, correspondence and multiple PGN time periods', () => {
    expect(gameTimeControl('30+1')).toBe('30 秒 + 1 秒/步');
    expect(gameTimeControl('1/172800')).toBe('每步 2 天');
    expect(gameTimeControl('40/7200:3600')).toBe('40 步 / 2 小时，1 小时');
    expect(gameTimeControl(null)).toBe('未记录');
    expect(gameTimeControl('-')).toBe('不限时');
  });
});
