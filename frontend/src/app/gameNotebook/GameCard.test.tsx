import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { GameResults } from './catalogApi';
import { GameCard } from './GameCard';
import { gameTimeControl } from './gameTimeControl';

describe('game catalog card', () => {
  it('shows both original ratings, the recorded terminal board, the opening and time control', () => {
    const game: GameResults['items'][number] = {
      id: 'game-12',
      white: 'White player',
      black: 'Black player',
      white_rating: 1863,
      black_rating: 1746,
      time_control: '300+3',
      final_fen: '7k/8/8/8/8/8/8/K7 w - - 12 43',
      opening_eco: 'D37',
      opening_name: 'Queen’s Gambit Declined',
      date: '2026.11.12',
      result: '1/2-1/2',
      platform: 'lichess',
      source_url: null,
      archived_at: null,
      created_at: '2026-11-13T00:00:00Z',
      version: 1,
      summary: '残局复盘',
    };
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
    expect(card.textContent).toContain('Queen’s Gambit Declined');
    expect(card.textContent).toContain('D37');
    const diagram = within(card).getByRole('img', {
      name: '实战主线的最终局面',
    });
    expect(diagram.getAttribute('data-fen')).toBe(game.final_fen);
    expect(diagram.querySelectorAll('text')).toHaveLength(2);
    expect(
      within(card).getByRole('link', { name: '打开棋谱' }).getAttribute('href'),
    ).toBe('/games/game-12');
  });

  it('handles fixed time, correspondence and multiple PGN time periods', () => {
    expect(gameTimeControl('30+1')).toBe('30 秒 + 1 秒/步');
    expect(gameTimeControl('1/172800')).toBe('每步 2 天');
    expect(gameTimeControl('40/7200:3600')).toBe('40 步 / 2 小时，1 小时');
    expect(gameTimeControl(null)).toBe('未记录');
    expect(gameTimeControl('-')).toBe('不限时');
  });
});
