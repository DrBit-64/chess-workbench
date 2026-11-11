import type { paths } from '../../types/api.generated';

export type SavedGame =
  paths['/api/notebook/games']['get']['responses'][200]['content']['application/json'][number];
export type GameResults =
  paths['/api/notebook/game-catalog']['get']['responses'][200]['content']['application/json'];
export type ImportPreview =
  paths['/api/notebook/imports/preview']['post']['responses'][200]['content']['application/json'];
export type ImportResult =
  paths['/api/notebook/imports']['post']['responses'][200]['content']['application/json'];
export type BookmarkResults =
  paths['/api/notebook/bookmarks']['get']['responses'][200]['content']['application/json'];
export type SavedBookmark = BookmarkResults['items'][number];
export type RelatedPositions =
  paths['/api/notebook/bookmarks/{bookmark_id}/occurrences']['get']['responses'][200]['content']['application/json'];
export const notebookApi = '/api/notebook';
