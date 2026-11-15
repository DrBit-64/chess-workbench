import { requestJson } from './client';
import type {
  Analysis,
  AnalysisCacheLookup,
  EngineCapabilities,
  EngineParameters,
} from './engineTypes';

export function analyzePosition(
  fen: string,
  parameters: EngineParameters,
  signal?: AbortSignal,
) {
  return requestJson<Analysis>('/api/engine/analyses', {
    method: 'POST',
    signal,
    body: JSON.stringify({ fen, parameters }),
  });
}

export function readEngineCapabilities(signal: AbortSignal) {
  return requestJson<EngineCapabilities>('/api/engine/capabilities', {
    method: 'GET',
    signal,
  });
}

export async function readPositionEvaluations(
  fens: readonly string[],
  parameters: EngineParameters,
  signal?: AbortSignal,
) {
  const scores = new Map<
    string,
    NonNullable<AnalysisCacheLookup['cached_scores']>[number]
  >();
  const missing: string[] = [];
  for (let i = 0; i < fens.length; i += 500) {
    const response = await requestJson<AnalysisCacheLookup>(
      '/api/engine/analyses/cache-lookup',
      {
        method: 'POST',
        signal,
        body: JSON.stringify({
          fens: fens.slice(i, i + 500),
          parameters,
          include_scores: true,
        }),
      },
    );
    for (const score of response.cached_scores ?? [])
      scores.set(score.fen, score);
    missing.push(...response.missing_fens);
  }
  return { scores, missing };
}
