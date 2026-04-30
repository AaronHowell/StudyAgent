import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { BookOpen, MessageSquare, Beaker, AlertCircle } from "lucide-react";
import { buildDocumentFileUrl } from "./PaperLabChatPanel";
import type { DocumentImage, ScannedDocument } from "./types";
import { useDocuments } from "./hooks/useDocuments";
import { usePreferences } from "./hooks/usePreferences";
import { useReproduction } from "./hooks/useReproduction";
import { PaperLibrary } from "./components/library/PaperLibrary";
import { PaperReader } from "./components/reader/PaperReader";
import { ChatPanel } from "./components/chat/ChatPanel";
import { ReproductionPanel } from "./components/agent/ReproductionPanel";
import { ContextMenu, ContextMenuItem } from "./components/common/ContextMenu";
import { GalleryModal } from "./components/common/GalleryModal";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

type WorkspaceView = "paper" | "ai";
type PaperView = "library" | "reader";
type GalleryImage = DocumentImage & { preview_url: string };

function App() {
  const { rootPath, projectId, setRootPath, setProjectId } = usePreferences();
  const docs = useDocuments();
  const repro = useReproduction();

  const [workspace, setWorkspace] = useState<WorkspaceView>("paper");
  const [paperView, setPaperView] = useState<PaperView>("library");
  const [selectedDocument, setSelectedDocument] = useState<ScannedDocument | null>(null);
  const [notesByDocumentId, setNotesByDocumentId] = useState<Record<string, string>>({});
  const [choosingFolder, setChoosingFolder] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [galleryImages, setGalleryImages] = useState<GalleryImage[]>([]);
  const [reproductionObjective, setReproductionObjective] = useState("尽可能复现当前论文，生成最小可运行代码和报告");

  const [contextMenu, setContextMenu] = useState<{
    visible: boolean; x: number; y: number; document: ScannedDocument | null;
  }>({ visible: false, x: 0, y: 0, document: null });

  const selectedPdfUrl = useMemo(
    () => (selectedDocument ? buildDocumentFileUrl(selectedDocument.path) : ""),
    [selectedDocument],
  );
  const selectedNote = selectedDocument ? notesByDocumentId[selectedDocument.id] ?? "" : "";

  // Initial scan
  useEffect(() => {
    if (rootPath) void docs.scan(rootPath);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (galleryOpen) { setGalleryOpen(false); cleanupGallery(); }
        else if (contextMenu.visible) closeContextMenu();
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [galleryOpen, contextMenu.visible]);

  // Cleanup gallery blob URLs
  useEffect(() => {
    return () => { for (const img of galleryImages) if (img.preview_url?.startsWith("blob:")) URL.revokeObjectURL(img.preview_url); };
  }, [galleryImages]);

  async function chooseProjectFolder() {
    setChoosingFolder(true);
    docs.setError("");
    try {
      const response = await fetch(`${apiBase}/desktop/project-folder/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_path: rootPath || undefined }),
      });
      if (!response.ok) throw new Error(await toApiErrorMessage(response));
      const payload = (await response.json()) as { path: string };
      if (!payload.path) return;
      setRootPath(payload.path);
      await docs.scan(payload.path);
    } catch (err) {
      docs.setError(err instanceof Error ? err.message : "选择项目目录失败");
    } finally {
      setChoosingFolder(false);
    }
  }

  function openReader(document: ScannedDocument) {
    setSelectedDocument(document);
    setPaperView("reader");
    setWorkspace("paper");
    closeContextMenu();
  }

  function closeReader() {
    setPaperView("library");
  }

  function updateSelectedNote(value: string) {
    if (!selectedDocument) return;
    setNotesByDocumentId((c) => ({ ...c, [selectedDocument.id]: value }));
  }

  function openContextMenu(event: MouseEvent, document: ScannedDocument) {
    event.preventDefault();
    event.stopPropagation();
    setSelectedDocument(document);
    setContextMenu({ visible: true, x: event.clientX, y: event.clientY, document });
  }

  function closeContextMenu() {
    setContextMenu({ visible: false, x: 0, y: 0, document: null });
  }

  async function openGallery(document: ScannedDocument) {
    closeContextMenu();
    setSelectedDocument(document);
    setGalleryOpen(true);
    setGalleryLoading(true);
    cleanupGallery();

    try {
      const response = await fetch(`${apiBase}/documents/images`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: document.path }),
      });
      if (!response.ok) throw new Error(await response.text());
      const payload = (await response.json()) as { images: DocumentImage[] };
      setGalleryImages(await buildGalleryImages(payload.images));
    } catch (err) {
      docs.setError(err instanceof Error ? err.message : "提取图片失败");
    } finally {
      setGalleryLoading(false);
    }
  }

  function cleanupGallery() {
    setGalleryImages((current) => {
      for (const img of current) if (img.preview_url?.startsWith("blob:")) URL.revokeObjectURL(img.preview_url);
      return [];
    });
  }

  async function buildGalleryImages(images: DocumentImage[]): Promise<GalleryImage[]> {
    const result: GalleryImage[] = [];
    for (const image of images) {
      let previewUrl = image.preview_data_url || "";
      if (!previewUrl && image.file_url) {
        const response = await fetch(`${apiBase}${image.file_url}`);
        if (!response.ok) throw new Error(`无法加载图片预览：${image.file_name}`);
        previewUrl = URL.createObjectURL(await response.blob());
      }
      result.push({ ...image, preview_url: previewUrl });
    }
    return result;
  }

  function getTaskState(document: ScannedDocument) {
    const task = docs.taskByPath[document.path];
    if (!task) return document.ingested ? "indexed" : "pending";
    return task.state;
  }

  function getActionLabel(document: ScannedDocument) {
    if (document.ingested) return "重新入库";
    const task = docs.taskByPath[document.path];
    if (task?.state === "failed") return "重试入库";
    if (task?.state === "queued" || task?.state === "running") return "正在入库";
    return "入库";
  }

  return (
    <main className="app-shell">
      {/* Header */}
      <header className="app-header">
        <div className="app-header-left">
          <div className="app-logo">
            <BookOpen size={18} />
            PaperLab
          </div>
          <div className="workspace-tabs" role="tablist" aria-label="工作区">
            <button
              className={`workspace-tab ${workspace === "paper" ? "active" : ""}`}
              role="tab"
              aria-selected={workspace === "paper"}
              onClick={() => setWorkspace("paper")}
            >
              <BookOpen size={14} />
              论文工作台
            </button>
            <button
              className={`workspace-tab ${workspace === "ai" ? "active" : ""}`}
              role="tab"
              aria-selected={workspace === "ai"}
              onClick={() => setWorkspace("ai")}
            >
              <MessageSquare size={14} />
              AI 对话
            </button>
          </div>
        </div>

        <div className="header-chips">
          <span className="chip">{projectId}</span>
          <span className="chip">已扫描 {docs.documents.length}</span>
          {docs.activeTaskCount > 0 ? (
            <span className="chip" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
              {docs.activeTaskCount} 个任务运行中
            </span>
          ) : null}
        </div>
      </header>

      {/* Error banner */}
      {docs.error ? (
        <div className="error-banner">
          <AlertCircle size={14} />
          {docs.error}
        </div>
      ) : null}

      {/* Content */}
      <div className="app-content">
        {workspace === "paper" ? (
          paperView === "library" ? (
            <PaperLibrary
              documents={docs.documents}
              taskByPath={docs.taskByPath}
              ingestingId={docs.ingestingId}
              batchIngesting={docs.batchIngesting}
              loading={docs.loading}
              pendingCount={docs.pendingCount}
              selectedId={selectedDocument?.id ?? null}
              rootPath={rootPath}
              projectId={projectId}
              onSelect={setSelectedDocument}
              onOpen={openReader}
              onIngest={(doc) => void docs.ingest(doc, projectId)}
              onBatchIngest={() => void docs.batchIngest(projectId)}
              onScan={() => void docs.scan(rootPath)}
              onChooseFolder={() => void chooseProjectFolder()}
              choosingFolder={choosingFolder}
              onContextMenu={openContextMenu}
            />
          ) : (
            <PaperReader
              document={selectedDocument}
              pdfUrl={selectedPdfUrl}
              projectId={projectId}
              note={selectedNote}
              onNoteChange={updateSelectedNote}
              onClose={closeReader}
              onOpenGallery={() => selectedDocument && void openGallery(selectedDocument)}
            />
          )
        ) : (
          /* AI workspace */
          <div className="layout-with-sidebar">
            {/* Left sidebar: reproduction panel */}
            <div className="sidebar" style={{ width: 300, overflowY: "auto" }}>
              <ReproductionPanel
                run={repro.run}
                loading={repro.loading}
                objective={reproductionObjective}
                onObjectiveChange={setReproductionObjective}
                onStart={() => void repro.start(projectId, reproductionObjective, selectedDocument ? [selectedDocument.id] : [])}
                onRefresh={() => void repro.refresh()}
                onPause={() => void repro.pause()}
                onResume={() => void repro.resume()}
                onCancel={() => void repro.cancel()}
                hasDocument={!!selectedDocument}
              />
            </div>

            {/* Main: chat */}
            <div className="main-content" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
              <ChatPanel
                projectId={projectId}
                title="AI 对话"
                description="解释论文、比较方法、规划复现步骤，都在同一个流式对话面板里完成。"
                placeholder="输入问题，或要求 AI 帮你做分析与复现规划"
                contextLabel={selectedDocument ? `当前选中论文：${selectedDocument.title}` : "当前未锁定具体论文"}
                showThreadSidebar
              />
            </div>
          </div>
        )}
      </div>

      {/* Context menu */}
      <ContextMenu
        visible={contextMenu.visible}
        x={contextMenu.x}
        y={contextMenu.y}
        onClose={closeContextMenu}
      >
        {contextMenu.document ? (
          <>
            <ContextMenuItem onClick={() => openReader(contextMenu.document!)}>
              打开阅读器
            </ContextMenuItem>
            <ContextMenuItem onClick={() => { void docs.ingest(contextMenu.document!, projectId); closeContextMenu(); }}>
              {getActionLabel(contextMenu.document)}
            </ContextMenuItem>
            <ContextMenuItem onClick={() => { void openGallery(contextMenu.document!); }}>
              查看图像画廊
            </ContextMenuItem>
          </>
        ) : null}
      </ContextMenu>

      {/* Gallery modal */}
      <GalleryModal
        open={galleryOpen}
        onClose={() => { setGalleryOpen(false); cleanupGallery(); }}
        title={selectedDocument?.title || "图像画廊"}
        subtitle={selectedDocument?.path}
        images={galleryImages}
        loading={galleryLoading}
      />
    </main>
  );
}

async function toApiErrorMessage(response: Response) {
  const raw = await response.text();
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch { /* use raw */ }
  if (response.status === 404) return "接口不可用，请重启后端到最新版本后重试。";
  return raw || "请求失败";
}

export default App;
