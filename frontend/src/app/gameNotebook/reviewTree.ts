import type { paths } from '../../types/api.generated';
import type { ReviewGame, ReviewNode } from './reviewTypes';

export type MoveUpdate =
  paths['/api/notebook/games/{game_id}/moves']['post']['responses'][200]['content']['application/json'];

export function indexReviewTree(nodes: ReviewNode[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map<string, ReviewNode[]>();
  for (const node of nodes) {
    if (!node.parent_id || node.hidden) continue;
    const siblings = children.get(node.parent_id) ?? [];
    siblings.push(node);
    children.set(node.parent_id, siblings);
  }
  for (const siblings of children.values())
    siblings.sort((a, b) => a.sort_order - b.sort_order);
  return { byId, children, root: nodes.find((n) => !n.parent_id) };
}

export function mergeTreeUpdate(
  previous: ReviewGame | undefined,
  change: MoveUpdate,
) {
  if (!previous || previous.version > change.game_version) return previous;
  const merged = new Map(previous.nodes.map((n) => [n.id, n]));
  for (const n of change.nodes) {
    const saved = merged.get(n.id);
    // A separately written note has its own optimistic-lock version.
    merged.set(
      n.id,
      saved && saved.version > n.version
        ? { ...n, note: saved.note, version: saved.version }
        : n,
    );
  }
  return {
    ...previous,
    nodes: [...merged.values()],
    version: change.game_version,
  };
}
