import { ArrowLeft, ImageIcon } from "lucide-react";
import type { ScannedDocument } from "../../types";
import { PdfViewer } from "./PdfViewer";
import { ChatPanel } from "../chat/ChatPanel";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function PaperReader({
  document,
  pdfUrl,
  projectId,
  note,
  onNoteChange,
  onClose,
  onOpenGallery,
}: {
  document: ScannedDocument | null;
  pdfUrl: string;
  projectId: string;
  note: string;
  onNoteChange: (value: string) => void;
  onClose: () => void;
  onOpenGallery: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <button className="btn btn-ghost btn-icon" onClick={onClose} title="返回论文库">
            <ArrowLeft size={16} />
          </button>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {document?.title || "论文阅读"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {document?.path || ""}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {document ? (
            <button className="btn btn-ghost btn-sm" onClick={onOpenGallery}>
              <ImageIcon size={14} />
              图像画廊
            </button>
          ) : null}
        </div>
      </div>

      {/* 3-column layout: notes | pdf | chat */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr 380px", flex: 1, minHeight: 0 }}>
        {/* Notes panel */}
        <div style={{ borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", background: "var(--sidebar-bg)" }}>
          <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-tertiary)" }}>
              论文笔记
            </span>
          </div>
          <textarea
            className="textarea"
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="记录论文贡献、问题、复现思路..."
            style={{ flex: 1, border: "none", borderRadius: 0, resize: "none", padding: 12, fontSize: 13, background: "transparent" }}
          />
        </div>

        {/* PDF viewer */}
        <div style={{ minWidth: 0, minHeight: 0 }}>
          {pdfUrl ? (
            <PdfViewer url={pdfUrl} />
          ) : (
            <div className="empty-state" style={{ height: "100%" }}>
              <strong>当前没有打开论文</strong>
              <p>回到论文库后双击论文，即可进入阅读状态。</p>
            </div>
          )}
        </div>

        {/* Chat panel */}
        <div style={{ borderLeft: "1px solid var(--border)", minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <ChatPanel
            projectId={projectId}
            title="论文助手"
            placeholder="输入你想让 AI 解释或分析的问题"
            contextLabel={document ? `当前论文：${document.title}` : ""}
            compact
          />
        </div>
      </div>
    </div>
  );
}
