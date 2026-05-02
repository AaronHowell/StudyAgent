import { useState } from "react";
import { ArrowLeft, ImageIcon, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import type { ScannedDocument } from "../../types";
import { PdfViewer } from "./PdfViewer";
import { ChatPanel } from "../chat/ChatPanel";

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
  const [notesOpen, setNotesOpen] = useState(true);
  const [chatOpen, setChatOpen] = useState(true);

  const gridCols = notesOpen && chatOpen
    ? "260px 1fr 380px"
    : notesOpen
      ? "260px 1fr 40px"
      : chatOpen
        ? "40px 1fr 380px"
        : "40px 1fr 40px";

  return (
    <div className="reader-container">
      {/* Header */}
      <div className="reader-header">
        <div className="reader-header-left">
          <button className="btn btn-ghost btn-icon" type="button" onClick={onClose} title="返回论文库">
            <ArrowLeft size={16} />
          </button>
          <div className="reader-header-info">
            <div className="reader-header-title">
              {document?.title || "论文阅读"}
            </div>
            <div className="reader-header-path">
              {document?.path || ""}
            </div>
          </div>
        </div>
        <div className="reader-header-actions">
          {document ? (
            <button className="btn btn-ghost btn-sm" type="button" onClick={onOpenGallery}>
              <ImageIcon size={14} />
              图像画廊
            </button>
          ) : null}
        </div>
      </div>

      {/* 3-column layout: notes | pdf | chat */}
      <div className="reader-body" style={{ gridTemplateColumns: gridCols }}>
        {/* Notes panel */}
        {notesOpen ? (
          <div className="reader-notes-panel">
            <div className="reader-notes-header">
              <span className="reader-notes-label">论文笔记</span>
              <button className="btn btn-ghost btn-icon btn-xs" type="button" onClick={() => setNotesOpen(false)} title="收起笔记">
                <PanelLeftClose size={14} />
              </button>
            </div>
            <textarea
              className="textarea"
              value={note}
              onChange={(e) => onNoteChange(e.target.value)}
              placeholder="记录论文贡献、问题、复现思路..."
              style={{ flex: 1, border: "none", borderRadius: 0, resize: "none", padding: 12, fontSize: 13, background: "transparent" }}
            />
          </div>
        ) : (
          <div className="reader-collapsed-strip">
            <button className="btn btn-ghost btn-icon btn-xs" type="button" onClick={() => setNotesOpen(true)} title="展开笔记">
              <PanelLeftOpen size={14} />
            </button>
          </div>
        )}

        {/* PDF viewer */}
        <div className="reader-pdf-area">
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
        {chatOpen ? (
          <div className="reader-chat-panel">
            <ChatPanel
              projectId={projectId}
              title="论文助手"
              placeholder="输入你想让 AI 解释或分析的问题"
              contextLabel={document ? `当前论文：${document.title}` : ""}
              compact
              collapseButton={
                <button className="btn btn-ghost btn-icon btn-xs" type="button" onClick={() => setChatOpen(false)} title="收起助手">
                  <PanelRightClose size={14} />
                </button>
              }
            />
          </div>
        ) : (
          <div className="reader-collapsed-strip">
            <button className="btn btn-ghost btn-icon btn-xs" type="button" onClick={() => setChatOpen(true)} title="展开助手">
              <PanelRightOpen size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
