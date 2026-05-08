import { FileText, Play, RotateCw, Sparkles } from "lucide-react";
import type { ScannedDocument } from "../../types";
import { StatusBadge } from "../common/StatusBadge";

export function PaperCard({
  document,
  state,
  selected,
  ingesting,
  metadataRefreshing,
  onSelect,
  onOpen,
  onIngest,
  onRefreshMetadata,
  onContextMenu,
}: {
  document: ScannedDocument;
  state: string;
  selected: boolean;
  ingesting: boolean;
  metadataRefreshing: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onIngest: () => void;
  onRefreshMetadata: () => void;
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
        <div className="paper-card-status">
          <StatusBadge state={state} />
          {document.metadata_source === "llm" ? (
            <span className="badge badge-info" title="已复用 LLM 元数据缓存">LLM</span>
          ) : null}
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
          <button
            className="btn btn-ghost btn-sm"
            disabled={metadataRefreshing}
            onClick={(e) => { e.stopPropagation(); onRefreshMetadata(); }}
            title="用 LLM 解析元数据"
          >
            <Sparkles size={12} />
            {metadataRefreshing ? "解析中" : "元数据"}
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
