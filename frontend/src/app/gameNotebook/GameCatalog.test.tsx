import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { SWRConfig } from 'swr';
import { expect, it, vi } from 'vitest';
import { GameCatalog } from './GameCatalog';

it('applies time controls and chronological order to the whole search and restores them after review', async () => {
  const seen: URLSearchParams[] = [];
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    seen.push(url.searchParams);
    return Response.json({
      items: [
        {
          id: 'example',
          white: 'Alice',
          black: 'Bob',
          date: '2026.01.01',
          result: '1-0',
          final_fen: '7k/8/8/8/8/8/8/K7 w - - 12 43',
          white_rating: 1500,
          black_rating: 1600,
          opening_eco: 'A00',
          opening_name: 'Example',
          time_control: '300+3',
          summary: '',
          platform: 'lichess',
        },
      ],
      total: 61,
      time_controls: ['180+0', '300+3', null],
    });
  });
  const origin = '/games?archived=1&q=Alice&page=2';
  function Review() {
    const location = useLocation();
    const navigate = useNavigate();
    return (
      <button onClick={() => navigate(-1)}>
        {location.state.notebookBack}
      </button>
    );
  }
  render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      <MemoryRouter initialEntries={[origin]}>
        <Routes>
          <Route path="/games" element={<GameCatalog />} />
          <Route path="/games/:game" element={<Review />} />
        </Routes>
      </MemoryRouter>
    </SWRConfig>,
  );
  await screen.findByRole('option', { name: '5+3' });
  expect(seen[0].get('offset')).toBe('30');
  fireEvent.change(screen.getByRole('combobox', { name: '对局时间排序' }), {
    target: { value: 'asc' },
  });
  await waitFor(() => expect(seen.at(-1)?.get('order')).toBe('asc'));
  expect(seen.at(-1)?.get('offset')).toBe('0');
  fireEvent.change(screen.getByRole('combobox', { name: '对局时限' }), {
    target: { value: '300+3' },
  });
  const open = await screen.findByRole('link', { name: '打开棋谱' });
  expect(Object.fromEntries(seen.at(-1)!)).toMatchObject({
    archived: 'true',
    q: 'Alice',
    offset: '0',
    order: 'asc',
    time_control: '300+3',
  });
  fireEvent.click(open);
  fireEvent.click(
    await screen.findByRole('button', {
      name: '/games?archived=1&q=Alice&order=asc&time_control=300%2B3',
    }),
  );
  expect(
    ((await screen.findByLabelText('对局时限')) as HTMLSelectElement).value,
  ).toBe('300+3');
  expect(
    (screen.getByLabelText('对局时间排序') as HTMLSelectElement).value,
  ).toBe('asc');
  expect((screen.getByLabelText('搜索棋谱') as HTMLInputElement).value).toBe(
    'Alice',
  );
  fireEvent.change(screen.getByLabelText('对局时限'), {
    target: { value: '' },
  });
  await waitFor(() =>
    expect((screen.getByLabelText('对局时限') as HTMLSelectElement).value).toBe(
      '',
    ),
  );
});
