import type { paths } from '../../types/api.generated';

export type HealthResponse =
  paths['/api/health']['get']['responses'][200]['content']['application/json'];
