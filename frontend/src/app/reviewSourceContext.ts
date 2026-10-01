import { createContext, useContext } from 'react';
import type {
  ReviewSourceIndex,
  SourceMoveTarget,
} from './reviewSourceCoverage';

export const ReviewSourceContext = createContext<{
  index: ReviewSourceIndex | null;
  onlyPending: boolean;
  focused: SourceMoveTarget | null;
  navigate: (target: SourceMoveTarget) => void;
}>({ index: null, onlyPending: false, focused: null, navigate: () => {} });
export const useReviewSource = () => useContext(ReviewSourceContext);
