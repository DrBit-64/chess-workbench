import { describe, expect, it } from 'vitest';
import type { PdfReviewDocument, PdfSourceEvidence } from '../logic/api/types';
import { reviewTheorySections } from './reviewTheorySections';

type ReviewItem = PdfReviewDocument['package']['items'][number];

const hashes = {
  example: 'a'.repeat(64),
  theory: 'b'.repeat(64),
  body: 'c'.repeat(64),
};

function node(
  id: string,
  parent_id: string | null,
  hash: string,
  page: number,
) {
  return {
    id,
    parent_id,
    validation_status: 'valid',
    evidence: [{ page, fragment_sha256: hash, start_offset: 0, end_offset: 3 }],
  };
}

describe('numbered theory review projection', () => {
  it('flags legal moves in the wrong source score and keeps blocked declarations distinct', () => {
    const source = {
      theory_sections: [
        {
          label: 'A',
          parent_label: null,
          body_source_ref: 's288_0',
          preview_source_refs: [],
          page: 288,
          opening_text: '6 f3',
        },
      ],
      pages: [
        {
          physical_page: 282,
          fragments: [
            { order: 0, fragment_sha256: hashes.example, text: '5...Nxc6' },
          ],
        },
        {
          physical_page: 287,
          fragments: [
            { order: 0, fragment_sha256: hashes.theory, text: '5...Nxc6' },
          ],
        },
        {
          physical_page: 288,
          fragments: [
            {
              order: 0,
              fragment_sha256: hashes.body,
              text: '6 f3 Bf5',
              declared_move_spans: [
                { start: 0, end: 3 },
                { start: 5, end: 8 },
              ],
              move_mentions: [
                { start: 0, end: 3, kind: 'candidate' },
                { start: 5, end: 8, kind: 'candidate' },
              ],
            },
          ],
        },
      ],
    } as unknown as PdfSourceEvidence;
    const items = [
      {
        kind: 'move_sequence',
        id: 'example',
        nodes: [
          node('old', null, hashes.example, 282),
          node('wrong', 'old', hashes.body, 288),
        ],
        annotations: [],
        reading_flow: [],
      },
      {
        kind: 'move_sequence',
        id: 'theory',
        nodes: [node('right', null, hashes.theory, 287)],
        annotations: [],
        reading_flow: [],
      },
    ] as unknown as ReviewItem[];
    const [status] = reviewTheorySections(source, items);
    expect(status.ownerSequenceId).toBe('theory');
    expect(status.wrongOwnerSequenceIds).toEqual(['example']);
    expect(status.wrongOwner).toBe(1);
    expect([status.declared, status.compiled, status.blocked]).toEqual([
      2, 1, 1,
    ]);
    expect(status.items).toHaveLength(1);
    expect(status.items[0].kind).toBe('move_sequence');
  });
});

describe('wrapped move declarations', () => {
  it('counts two source spans of one castle as one move', () => {
    const lead = '4'.repeat(64);
    const tail = '5'.repeat(64);
    const source = {
      theory_sections: [
        {
          label: 'D52',
          parent_label: 'D5',
          body_source_ref: 's317_0',
          preview_source_refs: [],
          page: 317,
          opening_text: '12...0-0-0',
        },
      ],
      pages: [
        {
          physical_page: 287,
          fragments: [
            { order: 0, fragment_sha256: hashes.theory, text: '5...Nxc6' },
          ],
        },
        {
          physical_page: 317,
          fragments: [
            {
              order: 0,
              fragment_sha256: lead,
              text: '0-',
              declared_move_spans: [{ start: 0, end: 2, token_id: 'castle' }],
            },
            {
              order: 1,
              fragment_sha256: tail,
              text: '0-0',
              declared_move_spans: [{ start: 0, end: 3, token_id: 'castle' }],
            },
          ],
        },
      ],
    } as unknown as PdfSourceEvidence;
    const items = [
      {
        kind: 'move_sequence',
        id: 'theory',
        nodes: [node('right', null, hashes.theory, 287)],
        annotations: [],
        reading_flow: [],
      },
      {
        kind: 'move_sequence',
        id: 'example',
        nodes: [
          {
            ...node('castle', null, tail, 317),
            evidence: [
              {
                page: 317,
                fragment_sha256: lead,
                start_offset: 0,
                end_offset: 2,
              },
              {
                page: 317,
                fragment_sha256: tail,
                start_offset: 0,
                end_offset: 3,
              },
            ],
          },
        ],
        annotations: [],
        reading_flow: [],
      },
    ] as unknown as ReviewItem[];
    const [status] = reviewTheorySections(source, items);
    expect([status.declared, status.compiled, status.blocked]).toEqual([
      1, 1, 0,
    ]);
  });
});
