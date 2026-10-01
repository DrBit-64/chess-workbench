import type { PdfReviewDocument, PdfSourceEvidence } from '../logic/api/types';
import { formatMoveNotation } from './moveNotation';

export type SourceReviewItem = NonNullable<
  PdfReviewDocument['package']['items']
>[number];
export type SourceEvidenceRef = SourceReviewItem['evidence'][number];
type SourceFragment = PdfSourceEvidence['pages'][number]['fragments'][number];
export interface SourceMoveTarget {
  sequenceId: string;
  nodeId: string;
}
export interface SourceMention {
  start: number;
  end: number;
  status: 'recorded' | 'pending' | 'plan' | 'mention';
  target?: SourceMoveTarget;
}
export interface ParagraphCoverage {
  mentions: SourceMention[];
  recorded: number;
  pending: number;
  plan: number;
  mention: number;
  unaligned: boolean;
}
export interface ReviewSourceIndex {
  fragments: Map<string, SourceFragment>;
  targets: Map<string, SourceMoveTarget[]>;
}
const fragmentKey = (page: number, hash: string) => `${page}:${hash}`;
const occurrenceKey = (
  page: number,
  hash: string,
  start: number,
  end: number,
) => `${fragmentKey(page, hash)}:${start}:${end}`;

// PDF offsets count Unicode code points; DOM string offsets count UTF-16 units.
const sourceSlice = (text: string, start: number, end: number) =>
  Array.from(text).slice(start, end).join('');
function notation(text: string): string {
  return formatMoveNotation(text)
    .move.replace(/[+#]+$/, '')
    .replace(/^([KQRBN]?)[a-h][1-8][-–]([a-h][1-8])$/, '$1$2');
}

export function buildReviewSourceIndex(
  items: SourceReviewItem[],
  source: PdfSourceEvidence,
): ReviewSourceIndex {
  const fragments = new Map<string, SourceFragment>();
  for (const page of source.pages)
    for (const fragment of page.fragments) {
      fragments.set(
        fragmentKey(page.physical_page, fragment.fragment_sha256),
        fragment,
      );
    }
  const targets = new Map<string, SourceMoveTarget[]>();
  for (const item of items) {
    if (item.kind !== 'move_sequence') continue;
    for (const node of item.nodes) {
      if (
        node.validation_status !== 'valid' ||
        !node.san_candidate ||
        !node.fen_after
      )
        continue;
      const occurrences = new Set<string>();
      for (const ref of node.evidence) {
        if (
          !ref.fragment_sha256 ||
          ref.start_offset == null ||
          ref.end_offset == null
        )
          continue;
        const fragment = fragments.get(
          fragmentKey(ref.page, ref.fragment_sha256),
        );
        if (!fragment) continue;
        for (const token of fragment.move_mentions ?? []) {
          if (token.start < ref.start_offset || token.end > ref.end_offset)
            continue;
          if (
            notation(sourceSlice(fragment.text, token.start, token.end)) !==
            notation(node.san_candidate)
          )
            continue;
          occurrences.add(
            occurrenceKey(
              ref.page,
              ref.fragment_sha256,
              token.start,
              token.end,
            ),
          );
        }
      }
      // Manual moves may cite a whole paragraph. Narrow it only if this SAN
      // has exactly one occurrence inside those cited ranges, not elsewhere.
      if (occurrences.size !== 1) continue;
      const key = [...occurrences][0];
      targets.set(key, [
        ...(targets.get(key) ?? []),
        { sequenceId: item.id, nodeId: node.id },
      ]);
    }
  }
  return { fragments, targets };
}

function normalized(text: string) {
  let value = '';
  const starts: number[] = [],
    ends: number[] = [];
  for (const match of text.matchAll(/\S+|\s+/gu)) {
    const offset = match.index;
    if (/^\s/.test(match[0])) {
      if (value && offset + match[0].length < text.length) {
        value += ' ';
        starts.push(offset);
        ends.push(offset + match[0].length);
      }
    } else {
      value += match[0];
      for (let index = 0; index < match[0].length; index++) {
        starts.push(offset + index);
        ends.push(offset + index + 1);
      }
    }
  }
  return { value, starts, ends };
}

export function paragraphCoverage(
  text: string,
  evidence: SourceEvidenceRef[],
  index: ReviewSourceIndex | null,
): ParagraphCoverage | null {
  if (!index) return null;
  const result: ParagraphCoverage = {
    mentions: [],
    recorded: 0,
    pending: 0,
    plan: 0,
    mention: 0,
    unaligned: false,
  };
  let joined = '';
  const mapped: {
    start: number;
    end: number;
    ref: SourceEvidenceRef;
    token: NonNullable<SourceFragment['move_mentions']>[number];
    fragment: SourceFragment;
  }[] = [];
  for (const ref of evidence) {
    const fragment = ref.fragment_sha256
      ? index.fragments.get(fragmentKey(ref.page, ref.fragment_sha256))
      : undefined;
    if (!fragment || ref.start_offset == null || ref.end_offset == null) {
      result.unaligned = true;
      continue;
    }
    if (joined) joined += ' ';
    const offset = joined.length;
    joined += sourceSlice(fragment.text, ref.start_offset, ref.end_offset);
    for (const token of fragment.move_mentions ?? []) {
      if (token.start < ref.start_offset || token.end > ref.end_offset)
        continue;
      mapped.push({
        start:
          offset +
          sourceSlice(fragment.text, ref.start_offset, token.start).length,
        end:
          offset +
          sourceSlice(fragment.text, ref.start_offset, token.end).length,
        ref,
        token,
        fragment,
      });
    }
  }
  const source = normalized(joined),
    shown = normalized(text);
  if (result.unaligned || !evidence.length || source.value !== shown.value) {
    return { ...result, unaligned: true };
  }
  for (const part of mapped) {
    const start = source.starts.indexOf(part.start),
      end = source.ends.indexOf(part.end);
    if (start < 0 || end < start) continue;
    const targets =
      index.targets.get(
        occurrenceKey(
          part.ref.page,
          part.fragment.fragment_sha256,
          part.token.start,
          part.token.end,
        ),
      ) ?? [];
    if (targets.length === 0 && part.token.kind === 'square') continue;
    const roles = part.fragment.roles ?? [];
    const exclusivelyNonScore =
      roles.length > 0 &&
      roles.every((role) => role === 'plan' || role === 'mention');
    const status =
      targets.length === 1
        ? 'recorded'
        : targets.length > 1
          ? 'pending'
          : exclusivelyNonScore && roles.includes('plan')
            ? 'plan'
            : exclusivelyNonScore && roles.includes('mention')
              ? 'mention'
              : 'pending';
    result[status]++;
    result.mentions.push({
      start: shown.starts[start],
      end: shown.ends[end],
      status,
      ...(targets.length === 1 ? { target: targets[0] } : {}),
    });
  }
  result.mentions.sort((left, right) => left.start - right.start);
  return result;
}

export function needsSourceReview(coverage: ParagraphCoverage | null): boolean {
  return coverage !== null && (coverage.unaligned || coverage.pending > 0);
}

export function combineCoverage(
  values: (ParagraphCoverage | null)[],
): ParagraphCoverage | null {
  const known = values.filter(
    (value): value is ParagraphCoverage => value !== null,
  );
  if (!known.length) return null;
  return {
    mentions: known.flatMap((value) => value.mentions),
    recorded: known.reduce((sum, value) => sum + value.recorded, 0),
    pending: known.reduce((sum, value) => sum + value.pending, 0),
    plan: known.reduce((sum, value) => sum + value.plan, 0),
    mention: known.reduce((sum, value) => sum + value.mention, 0),
    unaligned: known.some((value) => value.unaligned),
  };
}
