import { FileText, Play, RotateCw } from "lucide-react";
import type { ScannedDocument } from "../../types";
import { StatusBadge } from "../common/StatusBadge";

export function PaperCard({
  document,
  state,
  selected,
  ingesting,
  onSelect,
  onOpen,
  onIngest,
  onContextMenu,
}: {
  document: ScannedDocument;
  state: string;
  selected: boolean;
  ingesting: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onIngest: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  return (
    <article
      className={`paper-card ${selected ? "selected" : ""}`}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onContextMenu={onContextMenu}
    >
      <div className="paper-card-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="paper-card-title">{document.title}</div>
          <div className="paper-card-filename">{document.file_name}</div>
        </div>
        <FileText size={18} style={{ color: "var(--text-tertiary)", flexShrink: 0 }} />
      </div>

      <div className="paper-card-meta">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <StatusBadge state={state} />
          <span className="paper-card-date">{formatDate(document.modified_at)}</span>
        </div>
        <div className="paper-card-actions">
          <button
            className="btn btn-ghost btn-sm"
            onClick={(e) => { e.stopPropagation(); onOpen(); }}
            title="阅读"
          >
            <Play size={12} />
            阅读
          </button>
          <button
            className="btn btn-ghost btn-sm"
            disabled={ingesting}
            onClick={(e) => { e.stopPropagation(); onIngest(); }}
            title={document.ingested ? "重入库" : "入库"}
          >
            <RotateCw size={12} />
            {document.ingested ? "重入库" : "入库"}
          </button>
        </div>
      </div>
    </article>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN");
}
