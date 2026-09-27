import { parentheticalVariationRoots } from './variationPresentation';

export interface ScoreTreeLink {
  id: string;
  parentId: string | null;
  order: number;
}

export interface ScoreTreeVariation<T> {
  key: string;
  depth: number;
  path: string[];
  moves: T[];
  presentation: 'parenthetical' | 'rail';
}

export interface ScoreTreeLayout<T> {
  mainline: T[];
  variationsByParent: Map<string | null, ScoreTreeVariation<T>[]>;
}

/** Arrange one score by its chess parents, independent of source reading order. */
export function buildScoreTreeLayout<T>(
  moves: T[],
  rootParentId: string | null,
  linkOf: (move: T) => ScoreTreeLink,
): ScoreTreeLayout<T> {
  const links = moves.map(linkOf);
  const order = new Map(links.map((link, index) => [link.id, index]));
  const children = new Map<string | null, T[]>();
  for (const move of moves) {
    const parentId = linkOf(move).parentId;
    const siblings = children.get(parentId) ?? [];
    siblings.push(move);
    children.set(parentId, siblings);
  }
  for (const siblings of children.values()) {
    siblings.sort((left, right) => {
      const leftLink = linkOf(left);
      const rightLink = linkOf(right);
      return (
        leftLink.order - rightLink.order ||
        (order.get(leftLink.id) ?? 0) - (order.get(rightLink.id) ?? 0)
      );
    });
  }
  const parentheticalRoots = parentheticalVariationRoots(links);

  function primaryLine(parentId: string | null): T[] {
    const result: T[] = [];
    const visited = new Set<string | null>();
    let parent = parentId;
    while (!visited.has(parent)) {
      visited.add(parent);
      const primary = children.get(parent)?.[0];
      if (!primary) break;
      result.push(primary);
      parent = linkOf(primary).id;
    }
    return result;
  }

  const variationsByParent = new Map<string | null, ScoreTreeVariation<T>[]>();
  const indexed = new Set<string | null>();
  function indexTree(parentId: string | null, parentPath: string[]) {
    if (indexed.has(parentId)) return;
    indexed.add(parentId);
    const siblings = children.get(parentId) ?? [];
    const alternatives = siblings.slice(1).map((root) => {
      const rootId = linkOf(root).id;
      const path = [...parentPath, rootId];
      return {
        key: path.join('/'),
        depth: path.length,
        path,
        moves: [root, ...primaryLine(rootId)],
        presentation:
          path.length > 1 && parentheticalRoots.has(rootId)
            ? ('parenthetical' as const)
            : ('rail' as const),
      };
    });
    if (alternatives.length > 0) variationsByParent.set(parentId, alternatives);

    siblings.forEach((child, index) => {
      const childPath =
        index === 0 ? parentPath : [...parentPath, linkOf(child).id];
      indexTree(linkOf(child).id, childPath);
    });
  }
  indexTree(rootParentId, []);

  return { mainline: primaryLine(rootParentId), variationsByParent };
}
