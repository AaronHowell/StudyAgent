import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { PaperLabChatPanel, buildDocumentFileUrl } from "./PaperLabChatPanel";
import type { DocumentImage, ScannedDocument } from "./types";

type WorkspaceView = "paper" | "ai";
type PaperView = "library" | "reader";

type GalleryImage = DocumentImage & {
  preview_url: string;
};

type DesktopPreferences = {
  rootPath: string;
  projectId: string;
};

type IngestionTaskSummary = {
  task_id: string;
  project_id: string;
  path: string;
  state: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  result?: {
    document_id?: string;
    status?: string;
    message?: string;
    asset_count?: number;
    chunk_count?: number;
  } | null;
  error_message?: string;
  error_type?: string;
  error_code?: string;
  retryable?: boolean;
  timed_out?: boolean;
};

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";
const desktopPreferencesKey = "paperlab.desktop.preferences";
const documentsPerPage = 10;
const defaultPreferences: DesktopPreferences = {
  rootPath: "",
  projectId: "default-project",
};

function App() {
  const [initialPreferences] = useState(loadDesktopPreferences);
  const [workspace, setWorkspace] = useState<WorkspaceView>("paper");
  const [paperView, setPaperView] = useState<PaperView>("library");
  const [rootPath, setRootPath] = useState(initialPreferences.rootPath);
  const [projectId, setProjectId] = useState(initialPreferences.projectId);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
  const [choosingFolder, setChoosingFolder] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [documents, setDocuments] = useState<ScannedDocument[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<ScannedDocument | null>(null);
  const [documentImages, setDocumentImages] = useState<GalleryImage[]>([]);
  const [notesByDocumentId, setNotesByDocumentId] = useState<Record<string, string>>({});
  const [contextMenu, setContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
    document: ScannedDocument | null;
  }>({
    visible: false,
    x: 0,
    y: 0,
    document: null,
  });
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryDocument, setGalleryDocument] = useState<ScannedDocument | null>(null);
  const [ingestingDocumentId, setIngestingDocumentId] = useState<string | null>(null);
  const [batchIngesting, setBatchIngesting] = useState(false);
  const [taskByPath, setTaskByPath] = useState<Record<string, IngestionTaskSummary>>({});
  const [showAiProjectEditor, setShowAiProjectEditor] = useState(false);
  const [currentDocumentPage, setCurrentDocumentPage] = useState(1);

  const selectedPdfUrl = useMemo(
    () => (selectedDocument ? buildDocumentFileUrl(selectedDocument.path) : ""),
    [selectedDocument],
  );
  const selectedNote = selectedDocument ? notesByDocumentId[selectedDocument.id] ?? "" : "";
  const totalDocumentPages = Math.max(1, Math.ceil(documents.length / documentsPerPage));
  const paginatedDocuments = useMemo(() => {
    const startIndex = (currentDocumentPage - 1) * documentsPerPage;
    return documents.slice(startIndex, startIndex + documentsPerPage);
  }, [currentDocumentPage, documents]);

  useEffect(() => {
    saveDesktopPreferences({ rootPath, projectId });
  }, [rootPath, projectId]);

  useEffect(() => {
    void refreshTaskList();
  }, []);

  useEffect(() => {
    if (initialPreferences.rootPath) {
      void scanDocuments(initialPreferences.rootPath);
    }
  }, []);

  useEffect(() => {
    setCurrentDocumentPage((current) => Math.min(current, totalDocumentPages));
  }, [totalDocumentPages]);

  useEffect(() => {
    const handleWindowClick = () => {
      setContextMenu((current) => ({ ...current, visible: false, document: null }));
    };

    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setGalleryOpen(false);
        resetGalleryImages();
      }
    };

    window.addEventListener("click", handleWindowClick);
    window.addEventListener("keydown", handleEsc);
    return () => {
      window.removeEventListener("click", handleWindowClick);
      window.removeEventListener("keydown", handleEsc);
    };
  }, []);

  useEffect(() => {
    return () => {
      for (const image of documentImages) {
        if (image.preview_url && image.preview_url.startsWith("blob:")) {
          URL.revokeObjectURL(image.preview_url);
        }
      }
    };
  }, [documentImages]);

  useEffect(() => {
    let timer: number | undefined;
    const hasActiveTasks = Object.values(taskByPath).some(
      (task) => task.state === "queued" || task.state === "running",
    );

    if (!hasActiveTasks) {
      return;
    }

    timer = window.setInterval(() => {
      void refreshTaskList();
    }, 1500);

    return () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
    };
  }, [taskByPath]);

  async function chooseProjectFolder() {
    setChoosingFolder(true);
    setErrorMessage("");

    try {
      const response = await fetch(`${apiBase}/desktop/project-folder/select`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          current_path: rootPath || undefined,
        }),
      });

      if (!response.ok) {
        throw new Error(await toApiErrorMessage(response, "select-project-folder"));
      }

      const payload = (await response.json()) as { path: string };
      if (!payload.path) {
        return;
      }

      setRootPath(payload.path);
      await scanDocuments(payload.path);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "选择项目目录失败");
    } finally {
      setChoosingFolder(false);
    }
  }

  async function scanDocuments(targetRootPath = rootPath) {
    if (!targetRootPath) {
      setErrorMessage("请先选择项目目录。");
      return;
    }

    setLoadingDocuments(true);
    setErrorMessage("");

    try {
      const response = await fetch(`${apiBase}/documents/scan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          root_path: targetRootPath,
        }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as { documents: ScannedDocument[]; root_path?: string };
      const nextRootPath = payload.root_path || targetRootPath;
      setRootPath(nextRootPath);
      setDocuments(payload.documents);
      setCurrentDocumentPage(1);
      setSelectedDocument((current) =>
        payload.documents.find((document) => document.id === current?.id) ?? payload.documents[0] ?? null,
      );
      setPaperView("library");
      resetGalleryImages();
      await refreshTaskList();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "扫描论文失败");
    } finally {
      setLoadingDocuments(false);
    }
  }

  async function queueIngestion(document: ScannedDocument) {
    setIngestingDocumentId(document.id);
    setErrorMessage("");

    try {
      const response = await fetch(`${apiBase}/documents/ingest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: projectId,
          path: document.path,
        }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as { task: IngestionTaskSummary };
      setTaskByPath((current) => ({
        ...current,
        [document.path]: payload.task,
      }));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "提交入库失败");
    } finally {
      setIngestingDocumentId(null);
    }
  }

  async function batchIngestPendingDocuments() {
    const candidatePaths = documents
      .filter((document) => {
        const task = taskByPath[document.path];
        return !document.ingested && !isTaskActive(task);
      })
      .map((document) => document.path);

    if (candidatePaths.length === 0) {
      return;
    }

    setBatchIngesting(true);
    setErrorMessage("");
    try {
      const response = await fetch(`${apiBase}/documents/ingest/batch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: projectId,
          paths: candidatePaths,
        }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as { tasks: IngestionTaskSummary[] };
      setTaskByPath((current) => {
        const next = { ...current };
        for (const task of payload.tasks) {
          next[task.path] = task;
        }
        return next;
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量入库失败");
    } finally {
      setBatchIngesting(false);
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

  async function loadDocumentImages(document: ScannedDocument) {
    closeContextMenu();
    setSelectedDocument(document);
    setGalleryDocument(document);
    setGalleryOpen(true);
    setLoadingImages(true);
    setErrorMessage("");
    resetGalleryImages();

    try {
      const response = await fetch(`${apiBase}/documents/images`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: document.path }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as { images: DocumentImage[] };
      setDocumentImages(await buildGalleryImages(payload.images));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "提取图片失败");
    } finally {
      setLoadingImages(false);
    }
  }

  function updateSelectedNote(value: string) {
    if (!selectedDocument) {
      return;
    }
    setNotesByDocumentId((current) => ({
      ...current,
      [selectedDocument.id]: value,
    }));
  }

  function openContextMenu(event: MouseEvent, document: ScannedDocument) {
    event.preventDefault();
    event.stopPropagation();
    setSelectedDocument(document);
    setContextMenu({
      visible: true,
      x: event.clientX,
      y: event.clientY,
      document,
    });
  }

  function closeContextMenu() {
    setContextMenu({
      visible: false,
      x: 0,
      y: 0,
      document: null,
    });
  }

  function closeGallery() {
    setGalleryOpen(false);
    resetGalleryImages();
  }

  function resetGalleryImages() {
    setDocumentImages((current) => {
      for (const image of current) {
        if (image.preview_url && image.preview_url.startsWith("blob:")) {
          URL.revokeObjectURL(image.preview_url);
        }
      }
      return [];
    });
  }

  async function buildGalleryImages(images: DocumentImage[]): Promise<GalleryImage[]> {
    const result: GalleryImage[] = [];

    for (const image of images) {
      let previewUrl = image.preview_data_url || "";
      if (!previewUrl && image.file_url) {
        const response = await fetch(`${apiBase}${image.file_url}`);
        if (!response.ok) {
          throw new Error(`无法加载图片预览：${image.file_name}`);
        }
        const imageBlob = await response.blob();
        previewUrl = URL.createObjectURL(imageBlob);
      }

      result.push({
        ...image,
        preview_url: previewUrl,
      });
    }

    return result;
  }

  async function refreshTaskList() {
    try {
      const response = await fetch(`${apiBase}/documents/ingest`);
      if (!response.ok) {
        return;
      }

      const tasks = (await response.json()) as IngestionTaskSummary[];
      setTaskByPath(() => {
        const next: Record<string, IngestionTaskSummary> = {};
        for (const task of tasks) {
          next[task.path] = task;
        }
        return next;
      });

      setDocuments((current) =>
        current.map((document) => {
          const task = tasks.find((item) => item.path === document.path);
          if (!task) {
            return document;
          }
          if (task.state === "completed") {
            return { ...document, ingested: true };
          }
          return document;
        }),
      );
    } catch {
      // Keep current list when refresh fails.
    }
  }

  const activeTaskCount = Object.values(taskByPath).filter(
    (task) => task.state === "queued" || task.state === "running",
  ).length;
  const completedDocumentCount = documents.filter((document) => document.ingested).length;
  const pendingDocumentCount = documents.filter((document) => {
    const task = taskByPath[document.path];
    return !document.ingested && !isTaskActive(task);
  }).length;

  return (
    <main className="app-shell" onContextMenu={(event) => event.preventDefault()}>
      <header className="app-window-header">
        <div className="app-window-title-group">
          <div>
            <p className="app-kicker">PaperLab</p>
            <h1>{workspace === "paper" ? "论文工作台" : "AI 对话"}</h1>
          </div>
          <div className="workspace-tabs" role="tablist" aria-label="工作区">
            <button
              className={`workspace-tab ${workspace === "paper" ? "active" : ""}`}
              role="tab"
              aria-selected={workspace === "paper"}
              onClick={() => setWorkspace("paper")}
            >
              论文工作台
            </button>
            <button
              className={`workspace-tab ${workspace === "ai" ? "active" : ""}`}
              role="tab"
              aria-selected={workspace === "ai"}
              onClick={() => setWorkspace("ai")}
            >
              AI 对话
            </button>
          </div>
        </div>

        <div className="header-chip-row">
          <span className="chip">项目：{projectId}</span>
          <span className="chip">已扫描：{documents.length}</span>
          <span className="chip">运行中：{activeTaskCount}</span>
        </div>
      </header>

      {errorMessage ? <p className="error-message app-error-banner">{errorMessage}</p> : null}

      {workspace === "paper" ? (
        paperView === "library" ? (
          <section className="paper-library-layout">
            <aside className="workspace-panel library-sidebar">
              <div className="panel-block">
                <p className="section-kicker">项目</p>
                <h2>库管理</h2>
                <label className="field">
                  <span>项目目录</span>
                  <div className="folder-input-row">
                    <input
                      className="input"
                      value={rootPath}
                      onChange={(event) => setRootPath(event.target.value)}
                      placeholder="选择或输入本地项目目录"
                    />
                    <button className="button subtle small-button" onClick={() => void chooseProjectFolder()} disabled={choosingFolder}>
                      {choosingFolder ? "选择中..." : "选择文件夹"}
                    </button>
                  </div>
                </label>
                <label className="field">
                  <span>项目 ID</span>
                  <input className="input" value={projectId} onChange={(event) => setProjectId(event.target.value)} />
                </label>
                <div className="button-row">
                  <button className="button primary" onClick={() => void scanDocuments()} disabled={loadingDocuments}>
                    {loadingDocuments ? "扫描中..." : "刷新论文库"}
                  </button>
                  <button
                    className="button subtle"
                    onClick={() => void batchIngestPendingDocuments()}
                    disabled={batchIngesting || pendingDocumentCount === 0}
                  >
                    {batchIngesting ? "提交中..." : `批量入库 (${pendingDocumentCount})`}
                  </button>
                </div>
              </div>

              <div className="panel-block">
                <p className="section-kicker">概览</p>
                <div className="stats-list">
                  <div className="stat-row">
                    <span>已入库</span>
                    <strong>{completedDocumentCount}</strong>
                  </div>
                  <div className="stat-row">
                    <span>待入库</span>
                    <strong>{pendingDocumentCount}</strong>
                  </div>
                  <div className="stat-row">
                    <span>运行中任务</span>
                    <strong>{activeTaskCount}</strong>
                  </div>
                </div>
              </div>
            </aside>

            <section className="workspace-panel library-main">
              <div className="workspace-section-header">
                <div>
                  <p className="section-kicker">论文库</p>
                  <h2>论文列表</h2>
                  <p className="section-copy">双击论文进入阅读器，右键可直接执行入库操作。</p>
                </div>
                {documents.length > 0 ? (
                  <div className="table-meta-row">
                    <span className="chip">共 {documents.length} 篇</span>
                    <span className="chip">每页 {documentsPerPage} 篇</span>
                  </div>
                ) : null}
              </div>

              {documents.length === 0 ? (
                <div className="empty-state-card large">
                  <strong>还没有加载任何论文</strong>
                  <p>选择项目目录后点击“刷新论文库”，界面会自动把数据库里已有的入库状态同步回来。</p>
                </div>
              ) : (
                <div className="document-table-shell">
                  <table className="document-table">
                    <thead>
                      <tr>
                        <th>论文</th>
                        <th>状态</th>
                        <th>更新时间</th>
                        <th>路径</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedDocuments.map((document) => {
                        const task = taskByPath[document.path];
                        const state = renderTaskState(document, taskByPath);
                        return (
                          <tr
                            key={document.id}
                            className={selectedDocument?.id === document.id ? "selected" : ""}
                            onClick={() => setSelectedDocument(document)}
                            onDoubleClick={() => openReader(document)}
                            onContextMenu={(event) => openContextMenu(event, document)}
                          >
                            <td>
                              <div className="document-cell">
                                <strong>{document.title}</strong>
                                <span>{document.file_name}</span>
                              </div>
                            </td>
                            <td>
                              <StatusBadge state={state} />
                            </td>
                            <td>{formatDate(document.modified_at)}</td>
                            <td className="path-cell">{document.path}</td>
                            <td>
                              <div className="document-action-row">
                                <button className="mini-action" onClick={(event) => {
                                  event.stopPropagation();
                                  openReader(document);
                                }}>
                                  阅读
                                </button>
                                <button
                                  className="mini-action"
                                  disabled={isTaskActive(task) || ingestingDocumentId === document.id}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void queueIngestion(document);
                                  }}
                                >
                                  {document.ingested ? "重入库" : task?.state === "failed" ? "重试入库" : "入库"}
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {documents.length > documentsPerPage ? (
                <div className="pagination-row">
                  <span className="pagination-summary">
                    第 {currentDocumentPage} / {totalDocumentPages} 页
                  </span>
                  <div className="button-row">
                    <button
                      className="button subtle small-button"
                      onClick={() => setCurrentDocumentPage((page) => Math.max(1, page - 1))}
                      disabled={currentDocumentPage === 1}
                    >
                      上一页
                    </button>
                    <button
                      className="button subtle small-button"
                      onClick={() => setCurrentDocumentPage((page) => Math.min(totalDocumentPages, page + 1))}
                      disabled={currentDocumentPage === totalDocumentPages}
                    >
                      下一页
                    </button>
                  </div>
                </div>
              ) : null}

            </section>
          </section>
        ) : (
          <section className="reader-layout">
            <aside className="workspace-panel reader-note-panel">
              <div className="panel-block reader-note-block">
                <p className="section-kicker">论文笔记</p>
                <h2>论文笔记</h2>
                <textarea
                  className="input textarea note-textarea"
                  rows={18}
                  value={selectedNote}
                  onChange={(event) => updateSelectedNote(event.target.value)}
                  placeholder="记录论文贡献、问题、复现思路、实验疑点和后续待办"
                />
              </div>
            </aside>

            <section className="workspace-panel reader-main-panel">
              <div className="workspace-section-header">
                <div>
                  <p className="section-kicker">阅读器</p>
                  <h2>{selectedDocument?.title || "论文阅读"}</h2>
                  <p className="section-copy">{selectedDocument?.path || "请选择一篇论文进入阅读。"}</p>
                </div>
                <div className="button-row">
                  <button className="button subtle" onClick={closeReader}>
                    返回论文库
                  </button>
                  {selectedDocument ? (
                    <button className="button subtle" onClick={() => void loadDocumentImages(selectedDocument)}>
                      图像画廊
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="reader-frame">
                {selectedPdfUrl ? (
                  <iframe src={selectedPdfUrl} className="pdf-viewer" title="论文预览" />
                ) : (
                  <div className="empty-state-card large">
                    <strong>当前没有打开论文</strong>
                    <p>回到论文库后双击论文，即可进入阅读状态。</p>
                  </div>
                )}
              </div>
            </section>

            <aside className="workspace-panel reader-chat-panel">
              <div className="panel-block reader-chat-block">
                <PaperLabChatPanel
                  projectId={projectId}
                  title="论文助手"
                  description="针对当前论文提问、解释方法、梳理实验结论或规划复现。"
                  placeholder="输入你想让 AI 解释或分析的问题"
                  contextLabel={selectedDocument ? `当前论文：${selectedDocument.title}` : ""}
                />
              </div>
            </aside>
          </section>
        )
      ) : (
        <section className="ai-workspace-layout">
          <div className="workspace-panel ai-workspace-panel">
            <div className="workspace-section-header">
              <div>
                <p className="section-kicker">AI 工作区</p>
                <h2>AI 对话</h2>
                <p className="section-copy">左侧按项目和历史对话组织，右侧专注当前对话内容。</p>
              </div>
              <button className="button subtle" onClick={() => setShowAiProjectEditor((current) => !current)}>
                {showAiProjectEditor ? "收起项目设置" : "调整项目"}
              </button>
            </div>

            {showAiProjectEditor ? (
              <div className="ai-project-editor">
                <label className="field">
                  <span>项目目录</span>
                  <div className="folder-input-row">
                    <input className="input" value={rootPath} onChange={(event) => setRootPath(event.target.value)} />
                    <button className="button subtle small-button" onClick={() => void chooseProjectFolder()} disabled={choosingFolder}>
                      {choosingFolder ? "选择中..." : "选择文件夹"}
                    </button>
                  </div>
                </label>
                <label className="field">
                  <span>项目 ID</span>
                  <input className="input" value={projectId} onChange={(event) => setProjectId(event.target.value)} />
                </label>
                <button className="button primary small-button" onClick={() => void scanDocuments()} disabled={loadingDocuments}>
                  {loadingDocuments ? "刷新中..." : "刷新论文库"}
                </button>
              </div>
            ) : null}

            <PaperLabChatPanel
              projectId={projectId}
              title="AI 对话"
              description="解释论文、比较方法、规划复现步骤，都在同一个流式对话面板里完成。"
              placeholder="输入问题，或要求 AI 帮你做分析与复现规划"
              contextLabel={selectedDocument ? `当前选中论文：${selectedDocument.title}` : "当前未锁定具体论文"}
              showThreadSidebar
            />
          </div>
        </section>
      )}

      {contextMenu.visible && contextMenu.document ? (
        <div className="context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
          <button className="context-menu-item" onClick={() => openReader(contextMenu.document!)}>
            打开阅读器
          </button>
          <button className="context-menu-item" onClick={() => void queueIngestion(contextMenu.document!)}>
            {getDocumentActionLabel(contextMenu.document, taskByPath)}
          </button>
        </div>
      ) : null}

      {galleryOpen ? (
        <div className="modal-backdrop" onClick={closeGallery}>
          <section className="modal-panel" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="section-kicker">图像画廊</p>
                <h2>{galleryDocument?.title || "图像画廊"}</h2>
                <p className="section-copy">{galleryDocument?.path}</p>
              </div>
              <button className="button subtle" onClick={closeGallery}>
                关闭
              </button>
            </header>

            {loadingImages ? <p className="loading-copy">正在加载论文图片...</p> : null}
            {!loadingImages && documentImages.length === 0 ? (
              <div className="empty-state-card large">
                <strong>没有提取到图片</strong>
                <p>当前论文没有可展示的图像资源。</p>
              </div>
            ) : null}

            <div className="gallery-grid">
              {documentImages.map((image) => (
                <article className="gallery-card" key={image.id}>
                  {image.preview_url ? (
                    <img className="gallery-image" src={image.preview_url} alt={image.asset_label || image.file_name} loading="lazy" />
                  ) : (
                    <div className="gallery-image empty-image">预览不可用</div>
                  )}
                  <div className="gallery-copy">
                    <strong>{image.figure_label || image.asset_label || `第 ${image.page_number} 页`}</strong>
                    <p>{image.summary || image.caption || "没有图片摘要"}</p>
                    <small>{image.caption || `${image.asset_type} · 第 ${image.page_number} 页`}</small>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function loadDesktopPreferences(): DesktopPreferences {
  if (typeof window === "undefined") {
    return defaultPreferences;
  }

  const raw = window.localStorage.getItem(desktopPreferencesKey);
  if (!raw) {
    return defaultPreferences;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<DesktopPreferences>;
    return {
      rootPath: typeof parsed.rootPath === "string" ? parsed.rootPath : defaultPreferences.rootPath,
      projectId: typeof parsed.projectId === "string" && parsed.projectId ? parsed.projectId : defaultPreferences.projectId,
    };
  } catch {
    return defaultPreferences;
  }
}

function saveDesktopPreferences(preferences: DesktopPreferences) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(desktopPreferencesKey, JSON.stringify(preferences));
}

function StatusBadge({ state }: { state: string }) {
  return <span className={`status-badge state-${state.toLowerCase().replace(/\s+/g, "-")}`}>{humanizeState(state)}</span>;
}

function renderTaskState(document: ScannedDocument, taskByPath: Record<string, IngestionTaskSummary>) {
  const task = taskByPath[document.path];
  if (!task) {
    return document.ingested ? "indexed" : "pending";
  }
  return task.state;
}

function getDocumentActionLabel(
  document: ScannedDocument,
  taskByPath: Record<string, IngestionTaskSummary>,
) {
  const task = taskByPath[document.path];
  if (document.ingested) {
    return "重新入库";
  }
  if (task?.state === "failed") {
    return "重试入库";
  }
  if (isTaskActive(task)) {
    return "正在入库";
  }
  return "入库";
}

function isTaskActive(task?: IngestionTaskSummary | null) {
  return task?.state === "queued" || task?.state === "running";
}

function formatDate(value?: string | null) {
  if (!value) {
    return "未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN");
}

function humanizeState(value: string) {
  switch (value) {
    case "indexed":
      return "已入库";
    case "pending":
      return "待入库";
    case "queued":
      return "排队中";
    case "running":
      return "进行中";
    case "failed":
      return "失败";
    case "completed":
      return "完成";
    default:
      return value;
  }
}

async function toApiErrorMessage(response: Response, context: "select-project-folder") {
  const raw = await response.text();
  let detail = raw;

  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) {
      detail = parsed.detail;
    }
  } catch {
    // Keep raw response body when it is not JSON.
  }

  if (context === "select-project-folder" && response.status === 404) {
    return "项目目录选择接口不可用，请重启后端到最新版本后重试。";
  }

  return detail || "请求失败";
}

export default App;
