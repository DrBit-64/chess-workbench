import type { paths } from '../../types/api.generated';

export type ReviewGame =
  paths['/api/notebook/games/{game_id}']['get']['responses'][200]['content']['application/json'];
export type ReviewNode = ReviewGame['nodes'][number];
export type ReviewGameSummary =
  paths['/api/notebook/games/{game_id}']['patch']['responses'][200]['content']['application/json'];
export type {
  SavedBookmark as ReviewBookmark,
  BookmarkResults as ReviewBookmarks,
} from './catalogApi';

/** SAN numbering must respect games imported from a custom starting position. */
export function moveLabel(node: ReviewNode) {
  if (!node.san) return '起始局面';
  const fields = node.fen.split(' ');
  const move = Number(fields[5]);
  return fields[1] === 'w'
    ? `${move - 1}... ${node.san}`
    : `${move}. ${node.san}`;
}
