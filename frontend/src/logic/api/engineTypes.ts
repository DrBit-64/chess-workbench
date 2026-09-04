import type { paths } from '../../types/api.generated';

export type EngineCapabilities =
  paths['/api/engine/capabilities']['get']['responses'][200]['content']['application/json'];

export type Analysis =
  paths['/api/engine/analyses']['post']['responses'][200]['content']['application/json'];

export type AnalysisCacheLookup =
  paths['/api/engine/analyses/cache-lookup']['post']['responses'][200]['content']['application/json'];

export type EngineParameters = Required<Analysis['parameters']>;
export type AnalysisLine = Analysis['lines'][number];

export type Job =
  paths['/api/jobs/{job_id}']['get']['responses'][200]['content']['application/json'];

export type EngineGame =
  paths['/api/engine/games/{game_id}']['get']['responses'][200]['content']['application/json'];

export type EngineGameMove = EngineGame['moves'][number];

export type EngineGameReview =
  paths['/api/engine/games/{game_id}/review']['post']['responses'][200]['content']['application/json'];

export type ReviewFinding = EngineGameReview['findings'][number];
