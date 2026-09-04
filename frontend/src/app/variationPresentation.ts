export interface OrderedVariationNode {
  id: string;
  parentId: string | null;
  order: number;
}

/**
 * Match Lichess's compact inline-tree rule: the only secondary child of a
 * binary fork is parenthesized when its primary continuation stays short and
 * does not branch again. Longer or more complex alternatives keep rails.
 */
export function parentheticalVariationRoots(
  nodes: OrderedVariationNode[],
  maxDepth = 6,
): Set<string> {
  const inputOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const children = new Map<string | null, OrderedVariationNode[]>();
  for (const node of nodes) {
    const siblings = children.get(node.parentId) ?? [];
    siblings.push(node);
    children.set(node.parentId, siblings);
  }
  for (const siblings of children.values()) {
    siblings.sort(
      (left, right) =>
        left.order - right.order ||
        (inputOrder.get(left.id) ?? 0) - (inputOrder.get(right.id) ?? 0),
    );
  }

  const result = new Set<string>();
  for (const siblings of children.values()) {
    if (siblings.length !== 2) continue;
    const secondary = siblings[1];
    if (!hasBranchingWithin(secondary.id, maxDepth, children)) {
      result.add(secondary.id);
    }
  }
  return result;
}

function hasBranchingWithin(
  nodeId: string,
  remainingDepth: number,
  children: ReadonlyMap<string | null, OrderedVariationNode[]>,
): boolean {
  if (remainingDepth <= 0) return true;
  const descendants = children.get(nodeId) ?? [];
  if (descendants.length > 1) return true;
  return descendants[0] !== undefined
    ? hasBranchingWithin(descendants[0].id, remainingDepth - 1, children)
    : false;
}
