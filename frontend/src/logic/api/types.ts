import type { paths } from '../../types/api.generated';

export type HealthResponse =
  paths['/api/health']['get']['responses'][200]['content']['application/json'];

export type DashboardSummary =
  paths['/api/dashboard/summary']['get']['responses'][200]['content']['application/json'];

export type Course =
  paths['/api/courses']['get']['responses'][200]['content']['application/json'][number];

export type Source =
  paths['/api/sources']['get']['responses'][200]['content']['application/json'][number];

export type CourseModule =
  paths['/api/courses/{course_id}/modules']['get']['responses'][200]['content']['application/json'][number];

export type ModuleEditor =
  paths['/api/courses/{course_id}/editor/{module_id}']['get']['responses'][200]['content']['application/json'];

export type Occurrence =
  paths['/api/occurrences']['post']['responses'][201]['content']['application/json'];

export type KnowledgeNote =
  paths['/api/knowledge-notes']['get']['responses'][200]['content']['application/json'][number];

export type CitableSource =
  paths['/api/citable-sources']['get']['responses'][200]['content']['application/json'][number];

export type PdfAssetListResponse =
  paths['/api/pdf-assets']['get']['responses'][200]['content']['application/json'];

export type PdfAsset = PdfAssetListResponse['items'][number];

export type PdfAssetEnvelope =
  paths['/api/pdf-assets']['post']['responses'][201]['content']['application/json'];

export type PdfExtractionListResponse =
  paths['/api/pdf-extractions']['get']['responses'][200]['content']['application/json'];

export type PdfExtraction = PdfExtractionListResponse['items'][number];

export type PdfExtractionEnvelope =
  paths['/api/pdf-extractions']['post']['responses'][202]['content']['application/json'];

export type PdfReviewDocument =
  paths['/api/pdf-extractions/{run_id}/review']['get']['responses'][200]['content']['application/json'];

export type ContentHistory =
  paths['/api/history/{entity_type}/{entity_id}']['get']['responses'][200]['content']['application/json'];
