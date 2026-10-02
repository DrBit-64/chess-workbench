import type { PdfReviewDocument, PdfSourceEvidence } from '../logic/api/types';

type ReviewItem = PdfReviewDocument['package']['items'][number];
type MoveSequenceItem = Extract<ReviewItem, { kind: 'move_sequence' }>;
type TheorySection = NonNullable<PdfSourceEvidence['theory_sections']>[number];
type SourcePoint = { page: number; order: number };

function sourcePoint(ref: string | null): SourcePoint | null {
  const match = /^s(\d+)_(\d+)$/.exec(ref ?? '');
  return match ? { page: Number(match[1]), order: Number(match[2]) } : null;
}

function comparePoint(left: SourcePoint, right: SourcePoint): number {
  return left.page - right.page || left.order - right.order;
}

export type TheorySectionStatus = {
  section: TheorySection;
  declared: number;
  compiled: number;
  blocked: number;
  unexaminedCandidates: number;
  wrongOwner: number;
  wrongOwnerSequenceIds: string[];
  sourceFragmentHashes: string[];
  ownerSequenceId: string | null;
  firstMove: { sequenceId: string; nodeId: string } | null;
  items: ReviewItem[];
};

/** A source section is a reading range; it does not change the persisted chess graph. */
export function reviewTheorySections(
  source: PdfSourceEvidence,
  items: ReviewItem[],
): TheorySectionStatus[] {
  const sections = source.theory_sections ?? [];
  if (sections.length === 0) return [];
  const fragments = source.pages.flatMap((page) =>
    page.fragments.map((fragment) => ({
      ...fragment,
      page: page.physical_page,
      point: { page: page.physical_page, order: fragment.order },
    })),
  );
  const byHash = new Map(
    fragments.map((fragment) => [fragment.fragment_sha256, fragment.point]),
  );
  const sequences = items.filter(
    (item): item is MoveSequenceItem => item.kind === 'move_sequence',
  );
  const firstBody = sections
    .map((section) => sourcePoint(section.body_source_ref))
    .find(Boolean);
  let ownerSequenceId: string | null = null;
  let ownerLastPoint: SourcePoint | null = null;
  if (firstBody) {
    for (const sequence of sequences) {
      for (const node of sequence.nodes) {
        for (const evidence of node.evidence) {
          const point = byHash.get(evidence.fragment_sha256 ?? '');
          if (
            point &&
            comparePoint(point, firstBody) < 0 &&
            (ownerLastPoint === null || comparePoint(point, ownerLastPoint) > 0)
          ) {
            ownerLastPoint = point;
            ownerSequenceId = sequence.id;
          }
        }
      }
    }
  }
  return sections.map((section, index) => {
    const start = sourcePoint(section.body_source_ref);
    if (start === null) {
      return {
        section,
        declared: 0,
        compiled: 0,
        blocked: 0,
        unexaminedCandidates: 0,
        wrongOwner: 0,
        wrongOwnerSequenceIds: [],
        sourceFragmentHashes: [],
        ownerSequenceId,
        firstMove: null,
        items: [],
      };
    }
    const next = sections
      .slice(index + 1)
      .find(
        (candidate) =>
          candidate.body_source_ref &&
          !candidate.label.startsWith(section.label),
      );
    const end = sourcePoint(next?.body_source_ref ?? null);
    const within = (point: SourcePoint | undefined): boolean =>
      point !== undefined &&
      comparePoint(point, start) >= 0 &&
      (end === null || comparePoint(point, end) < 0);
    const visibleFragments = fragments.filter((fragment) =>
      within(fragment.point),
    );
    const evidenceKeys = new Set(
      visibleFragments.map((fragment) => fragment.fragment_sha256),
    );
    const declarations = new Map<string, string[]>();
    for (const fragment of visibleFragments) {
      for (const span of fragment.declared_move_spans ?? []) {
        const key = `${fragment.fragment_sha256}:${span.start}:${span.end}`;
        const tokenId = span.token_id ?? key;
        declarations.set(tokenId, [...(declarations.get(tokenId) ?? []), key]);
      }
    }
    const declaredKeys = new Set([...declarations.values()].flat());
    const compiledKeys = new Set<string>();
    const compiledByOwner = new Map<string, number>();
    const visibleItems: ReviewItem[] = [];
    let firstMove: TheorySectionStatus['firstMove'] = null;
    for (const item of items) {
      if (item.kind !== 'move_sequence') {
        if (
          item.evidence.some((ref) =>
            evidenceKeys.has(ref.fragment_sha256 ?? ''),
          )
        )
          visibleItems.push(item);
        continue;
      }
      const directNodes = item.nodes.filter((node) =>
        node.evidence.some((ref) =>
          evidenceKeys.has(ref.fragment_sha256 ?? ''),
        ),
      );
      if (directNodes.length === 0) continue;
      if (firstMove === null)
        firstMove = { sequenceId: item.id, nodeId: directNodes[0].id };
      compiledByOwner.set(
        item.id,
        directNodes.filter((node) => node.validation_status === 'valid').length,
      );
      for (const node of directNodes) {
        if (node.validation_status !== 'valid') continue;
        for (const evidence of node.evidence) {
          const key = `${evidence.fragment_sha256}:${evidence.start_offset}:${evidence.end_offset}`;
          if (declaredKeys.has(key)) compiledKeys.add(key);
        }
      }
      const nodeById = new Map(item.nodes.map((node) => [node.id, node]));
      const visibleIds = new Set(directNodes.map((node) => node.id));
      for (const node of directNodes) {
        let parentId = node.parent_id;
        while (parentId !== null && !visibleIds.has(parentId)) {
          visibleIds.add(parentId);
          parentId = nodeById.get(parentId)?.parent_id ?? null;
        }
      }
      visibleItems.push({
        ...item,
        nodes: item.nodes.filter((node) => visibleIds.has(node.id)),
        annotations: [],
        reading_flow: (item.reading_flow ?? []).filter(
          (entry) => entry.kind === 'move' && visibleIds.has(entry.node_id),
        ),
      });
    }
    const unexaminedCandidates = visibleFragments.reduce(
      (total, fragment) =>
        total +
        (fragment.move_mentions ?? []).filter((mention) => {
          if (mention.kind !== 'candidate') return false;
          const key = `${fragment.fragment_sha256}:${mention.start}:${mention.end}`;
          return !declaredKeys.has(key) && !compiledKeys.has(key);
        }).length,
      0,
    );
    const compiled = [...declarations.values()].filter((spans) =>
      spans.every((key) => compiledKeys.has(key)),
    ).length;
    const wrongOwnerSequenceIds = [...compiledByOwner]
      .filter(
        ([sequenceId, count]) =>
          ownerSequenceId && sequenceId !== ownerSequenceId && count > 0,
      )
      .map(([sequenceId]) => sequenceId);
    return {
      section,
      declared: declarations.size,
      compiled,
      blocked: declarations.size - compiled,
      unexaminedCandidates,
      wrongOwnerSequenceIds,
      sourceFragmentHashes: [...evidenceKeys],
      wrongOwner: [...compiledByOwner].reduce(
        (total, [sequenceId, count]) =>
          total +
          (ownerSequenceId && sequenceId !== ownerSequenceId ? count : 0),
        0,
      ),
      ownerSequenceId,
      firstMove,
      items: visibleItems,
    };
  });
}
