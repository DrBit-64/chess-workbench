import { Button } from 'antd';
import { NotebookDialog } from './NotebookDialog';

export function PromotionDialog({
  onChoose,
  onClose,
}: {
  onChoose: (piece: string) => void;
  onClose: () => void;
}) {
  return (
    <NotebookDialog title="选择升变棋子" onClose={onClose}>
      <div className="nb-actions">
        {Object.entries({ q: '后', r: '车', b: '象', n: '马' }).map(
          ([piece, name]) => (
            <Button key={piece} onClick={() => onChoose(piece)}>
              {name}
            </Button>
          ),
        )}
      </div>
    </NotebookDialog>
  );
}
