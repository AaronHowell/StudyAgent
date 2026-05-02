import { useState, useMemo } from "react";
import { FolderOpen, RefreshCw, Layers, ChevronLeft, ChevronRight } from "lucide-react";
import type { ScannedDocument } from "../../types";
import type { IngestionTaskSummary } from "../../hooks/useDocuments";
import { PaperCard } from "./PaperCard";
import { EmptyState } from "../common/EmptyState";

const ITEMS_PER_PAGE = 12;

export function PaperLibrary({
  documents,
  taskByPath,
  ingestingId,
  batchIngesting,
  loading,
  pendingCount,
  selectedId,
  rootPath,
  projectId,
  onSelect,
  onOpen,
  onIngest,
  onBatchIngest,
  onScan,
  onChooseFolder,
  choosingFolder,
  onContextMenu,
}: {
  documents: ScannedDocument[];
  taskByPath: Record<string, IngestionTaskSummary>;
  ingestingId: string | null;
  batchIngesting: boolean;
  loading: boolean;
  pendingCount: number;
  selectedId: string | null;
  rootPath: string;
  projectId: string;
  onSelect: (doc: ScannedDocument) => void;
  onOpen: (doc: ScannedDocument) => void;
  onIngest: (doc: ScannedDocument) => void;
  onBatchIngest: () => void;
  onScan: () => void;
  onChooseFolder: () => void;
  choosingFolder: boolean;
  onContextMenu: (e: React.MouseEvent, doc: ScannedDocument) => void;
}) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter(
      (d) => d.title.toLowerCase().includes(q) || d.file_name.toLowerCase().includes(q),
    );
  }, [documents, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const paginated = filtered.slice((safePage - 1) * ITEMS_PER_PAGE, safePage * ITEMS_PER_PAGE);

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {/* Sidebar */}
      <div className="sidebar sidebar-bottom">
        <div className="sidebar-section">
          <span className="sidebar-section-title">项目</span>
          <div style={{ padding: "4px 8px" }}>
            <div className="field" style={{ marginBottom: 8 }}>
              <span className="field-label">项目目录</span>
              <div style={{ display: "flex", gap: 4 }}>
                <input
                  className="input"
                  value={rootPath}
                  onChange={(e) => onSelect({ ...documents[0], path: e.target.value } as ScannedDocument)}
                  placeholder="选择目录"
                  style={{ fontSize: 12 }}
                />
                <button className="btn btn-sm" onClick={onChooseFolder} disabled={choosingFolder}>
                  <FolderOpen size={14} />
                </button>
              </div>
            </div>
            <div className="field" style={{ marginBottom: 12 }}>
              <span className="field-label">项目 ID</span>
              <input className="input" value={projectId} readOnly style={{ fontSize: 12 }} />
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <button className="btn btn-primary btn-sm" onClick={onScan} disabled={loading} style={{ flex: 1 }}>
                <RefreshCw size={12} />
                {loading ? "扫描中..." : "刷新"}
              </button>
              <button
                className="btn btn-sm"
                onClick={onBatchIngest}
                disabled={batchIngesting || pendingCount === 0}
                style={{ flex: 1 }}
              >
                <Layers size={12} />
                {batchIngesting ? "提交中..." : `批量入库 (${pendingCount})`}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="main-content" style={{ padding: 16 }}>
        {/* Search bar */}
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
          <input
            className="input"
            placeholder="搜索论文..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            style={{ maxWidth: 320 }}
          />
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            共 {filtered.length} 篇
          </span>
        </div>

        {/* Card grid */}
        {filtered.length === 0 ? (
          <EmptyState
            title="还没有加载任何论文"
            description="选择项目目录后点击刷新，界面会自动同步入库状态。"
          />
        ) : (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 12,
              }}
            >
              {paginated.map((doc) => {
                const task = taskByPath[doc.path];
                const state = task ? task.state : doc.ingested ? "indexed" : "pending";
                return (
                  <PaperCard
                    key={doc.id}
                    document={doc}
                    state={state}
                    selected={doc.id === selectedId}
                    ingesting={ingestingId === doc.id}
                    onSelect={() => onSelect(doc)}
                    onOpen={() => onOpen(doc)}
                    onIngest={() => onIngest(doc)}
                    onContextMenu={(e) => onContextMenu(e, doc)}
                  />
                );
              })}
            </div>

            {/* Pagination */}
            {totalPages > 1 ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 16 }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  title="上一页"
                >
                  <ChevronLeft size={14} />
                </button>
                <span style={{ fontSize: 12, color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
                  {safePage} / {totalPages}
                </span>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  title="下一页"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
