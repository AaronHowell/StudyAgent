import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { PaperLabChatPanel, buildDocumentFileUrl } from "./PaperLabChatPanel";
import type { DocumentImage, ScannedDocument } from "./types";

type WorkspaceView = "paper" | "ai";
type PaperView = "library" | "reader";
type TaskFilter = "all" | "active" | "failed" | "completed";

type GalleryImage = DocumentImage & {
  preview_url: string;
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

const apiBase =
  import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

function App() {
  const [workspace, setWorkspace] = useState<WorkspaceView>("paper");
  const [paperView, setPaperView] = useState<PaperView>("library");
  const [rootPath, setRootPath] = useState("C:\\Users\\Aaron_Howell\\Desktop\\postgraduate");
  const [projectId, setProjectId] = useState("frontend-project");
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
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
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("all");

  const selectedPdfUrl = useMemo(() => {
    if (!selectedDocument) {
      return "";
    }
    return buildDocumentFileUrl(selectedDocument.path);
  }, [selectedDocument]);

  const selectedNote = selectedDocument ? notesByDocumentId[selectedDocument.id] ?? "" : "";
  const pendingDocumentCount = useMemo(
    () =>
      documents.filter((document) => {
        const task = getTaskForDocument(document, taskByPath);
        return !document.ingested && !isTaskActive(task);
      }).length,
    [documents, taskByPath],
  );
  const activeTaskCount = useMemo(
    () =>
      Object.values(taskByPath).filter((task) => task.state === "queued" || task.state === "running")
        .length,
    [taskByPath],
  );
  const completedDocumentCount = useMemo(
    () => documents.filter((document) => document.ingested).length,
    [documents],
  );
  const orderedTasks = useMemo(
    () =>
      Object.values(taskByPath).sort((left, right) =>
        right.created_at.localeCompare(left.created_at),
      ),
    [taskByPath],
  );
  const filteredTasks = useMemo(() => {
    switch (taskFilter) {
      case "active":
        return orderedTasks.filter((task) => task.state === "queued" || task.state === "running");
      case "failed":
        return orderedTasks.filter((task) => task.state === "failed");
      case "completed":
        return orderedTasks.filter((task) => task.state === "completed");
      default:
        return orderedTasks;
    }
  }, [orderedTasks, taskFilter]);

  useEffect(() => {
    void refreshTaskList();
  }, []);

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
        if (image.preview_url) {
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

  async function scanDocuments() {
    setLoadingDocuments(true);
    setErrorMessage("");

    try {
      const response = await fetch(`${apiBase}/documents/scan`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          root_path: rootPath,
        }),
      });

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as { documents: ScannedDocument[] };
      setDocuments(payload.documents);
      setSelectedDocument(payload.documents[0] ?? null);
      setPaperView("library");
      resetGalleryImages();
      await refreshTaskList();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scan failed");
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
      setErrorMessage(error instanceof Error ? error.message : "Ingestion failed");
    } finally {
      setIngestingDocumentId(null);
    }
  }

  async function retryTask(task: IngestionTaskSummary) {
    const targetDocument = documents.find((document) => document.path === task.path);
    if (!targetDocument) {
      setErrorMessage("Cannot retry this task because the document is not in the current list.");
      return;
    }

    await queueIngestion(targetDocument);
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
      setErrorMessage(error instanceof Error ? error.message : "Batch ingestion failed");
    } finally {
      setBatchIngesting(false);
    }
  }

  function focusDocument(document: ScannedDocument) {
    setSelectedDocument(document);
    setWorkspace("paper");
  }

  function openReader(document: ScannedDocument) {
    setSelectedDocument(document);
    setPaperView("reader");
    setWorkspace("paper");
    closeContextMenu();
  }

  function backToLibrary() {
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
      const images = await buildGalleryImages(payload.images);
      setDocumentImages(images);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Image extraction failed");
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
        if (image.preview_url) {
          URL.revokeObjectURL(image.preview_url);
        }
      }
      return [];
    });
  }

  async function buildGalleryImages(images: DocumentImage[]): Promise<GalleryImage[]> {
    const result: GalleryImage[] = [];

    for (const image of images) {
      let previewUrl = "";
      if (image.file_url) {
        const response = await fetch(`${apiBase}${image.file_url}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch image preview: ${image.file_name}`);
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
      // Keep the current state if the task refresh fails.
    }
  }

  const currentTask = selectedDocument ? taskByPath[selectedDocument.path] : undefined;
  const selectedDocumentState = selectedDocument
    ? renderTaskState(selectedDocument, taskByPath)
    : "No paper selected";

  return (
    <main className="app-shell" onContextMenu={(event) => event.preventDefault()}>
      <header className="app-shell-header">
        <div className="app-brand">
          <p className="app-kicker">PaperLab Desktop</p>
          <h1>Research Control Center</h1>
          <p className="app-subtitle">
            Read papers, inspect figures, and direct the same AI assistant from either a paper-first
            desk or a pure research console.
          </p>
        </div>

        <div className="app-shell-meta">
          <div className="project-chip-group">
            <span className="chip">Project: {projectId}</span>
            <span className="chip">Papers: {documents.length}</span>
            <span className="chip">Active Tasks: {activeTaskCount}</span>
          </div>
          <div className="workspace-tabs" role="tablist" aria-label="Workspaces">
            <button
              className={`workspace-tab ${workspace === "paper" ? "active" : ""}`}
              role="tab"
              id="paper-workspace-tab"
              aria-selected={workspace === "paper"}
              aria-controls="paper-workspace-panel"
              onClick={() => setWorkspace("paper")}
            >
              Paper Workspace
            </button>
            <button
              className={`workspace-tab ${workspace === "ai" ? "active" : ""}`}
              role="tab"
              id="ai-workspace-tab"
              aria-selected={workspace === "ai"}
              aria-controls="ai-workspace-panel"
              onClick={() => setWorkspace("ai")}
            >
              AI Workspace
            </button>
          </div>
        </div>
      </header>

      {errorMessage ? <p className="error-message app-error-banner">{errorMessage}</p> : null}

      {workspace === "paper" ? (
        <section
          className="paper-workspace"
          id="paper-workspace-panel"
          role="tabpanel"
          aria-labelledby="paper-workspace-tab"
        >
          <aside className="workspace-panel desk-sidebar">
            <section className="panel-section control-panel">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Workspace Setup</p>
                  <h2>Library Control</h2>
                </div>
                <span className="chip">Default Desk</span>
              </div>

              <label className="field">
                <span>Project Folder</span>
                <input
                  className="input"
                  value={rootPath}
                  onChange={(event) => setRootPath(event.target.value)}
                />
              </label>

              <label className="field">
                <span>Project Id</span>
                <input
                  className="input"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                />
              </label>

              <div className="button-row">
                <button className="button primary" onClick={scanDocuments} disabled={loadingDocuments}>
                  {loadingDocuments ? "Scanning..." : "Scan Papers"}
                </button>
                <button
                  className="button subtle"
                  onClick={batchIngestPendingDocuments}
                  disabled={batchIngesting || pendingDocumentCount === 0}
                >
                  {batchIngesting ? "Queueing..." : `Batch Ingest (${pendingDocumentCount})`}
                </button>
              </div>
            </section>

            <section className="panel-section summary-grid">
              <article className="summary-card">
                <span className="summary-label">Indexed</span>
                <strong>{completedDocumentCount}</strong>
                <p>papers ready for grounded retrieval</p>
              </article>
              <article className="summary-card">
                <span className="summary-label">Pending</span>
                <strong>{pendingDocumentCount}</strong>
                <p>papers still waiting for ingestion</p>
              </article>
              <article className="summary-card">
                <span className="summary-label">Running</span>
                <strong>{activeTaskCount}</strong>
                <p>jobs currently executing</p>
              </article>
            </section>

            <section className="panel-section document-list-section">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Library</p>
                  <h2>Paper Queue</h2>
                </div>
                <span className="chip">{documents.length}</span>
              </div>

              {documents.length === 0 ? (
                <div className="empty-state-card">
                  <strong>No papers loaded</strong>
                  <p>Scan your project folder to populate the reading desk.</p>
                </div>
              ) : (
                <div className="document-list">
                  {documents.map((document) => {
                    const task = getTaskForDocument(document, taskByPath);
                    const state = renderTaskState(document, taskByPath);
                    const active = selectedDocument?.id === document.id;
                    return (
                      <article
                        key={document.id}
                        className={`document-row ${active ? "is-selected" : ""}`}
                        onClick={() => focusDocument(document)}
                        onDoubleClick={() => openReader(document)}
                        onContextMenu={(event) => openContextMenu(event, document)}
                      >
                        <div className="document-row-header">
                          <div>
                            <strong>{document.title}</strong>
                            <p>{document.file_name}</p>
                          </div>
                          <StatusBadge state={state} />
                        </div>
                        <p className="document-meta">{formatDate(document.modified_at)}</p>
                        <p className="document-path">{document.path}</p>
                        <div className="document-inline-actions">
                          <button
                            className="mini-action"
                            onClick={(event) => {
                              event.stopPropagation();
                              openReader(document);
                            }}
                          >
                            Open
                          </button>
                          <button
                            className="mini-action"
                            onClick={(event) => {
                              event.stopPropagation();
                              void loadDocumentImages(document);
                            }}
                          >
                            Gallery
                          </button>
                          <button
                            className="mini-action"
                            disabled={isTaskActive(task) || ingestingDocumentId === document.id}
                            onClick={(event) => {
                              event.stopPropagation();
                              void queueIngestion(document);
                            }}
                          >
                            {document.ingested ? "Re-ingest" : task?.state === "failed" ? "Retry" : "Ingest"}
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>
          </aside>

          <section className="workspace-panel desk-main">
            {paperView === "reader" && selectedDocument ? (
              <section className="reader-panel">
                <div className="workspace-toolbar">
                  <div>
                    <p className="section-kicker">Reader</p>
                    <h2>{selectedDocument.title}</h2>
                    <p className="toolbar-copy">{selectedDocument.path}</p>
                  </div>
                  <div className="button-row">
                    <button className="button subtle" onClick={backToLibrary}>
                      Back to Library
                    </button>
                    <button
                      className="button subtle"
                      onClick={() => void loadDocumentImages(selectedDocument)}
                    >
                      Figure Gallery
                    </button>
                  </div>
                </div>

                <div className="reader-frame">
                  {selectedPdfUrl ? (
                    <iframe src={selectedPdfUrl} className="pdf-viewer" title="PDF Viewer" />
                  ) : (
                    <div className="empty-state-card">
                      <strong>No active reader</strong>
                      <p>Select a paper from the library to open the reader.</p>
                    </div>
                  )}
                </div>
              </section>
            ) : (
              <section className="desk-overview">
                <div className="workspace-toolbar">
                  <div>
                    <p className="section-kicker">Paper Workspace</p>
                    <h2>Research Desk</h2>
                    <p className="toolbar-copy">
                      Keep the paper list, reading surface, and grounded assistant aligned around the
                      current document.
                    </p>
                  </div>
                  <div className="button-row">
                    <button
                      className="button primary"
                      onClick={() => selectedDocument && openReader(selectedDocument)}
                      disabled={!selectedDocument}
                    >
                      Open Reader
                    </button>
                    <button
                      className="button subtle"
                      onClick={() => selectedDocument && void loadDocumentImages(selectedDocument)}
                      disabled={!selectedDocument}
                    >
                      Figure Gallery
                    </button>
                    <button
                      className="button subtle"
                      onClick={() => selectedDocument && void queueIngestion(selectedDocument)}
                      disabled={!selectedDocument || isTaskActive(currentTask) || ingestingDocumentId === selectedDocument?.id}
                    >
                      {selectedDocument?.ingested
                        ? "Re-ingest Paper"
                        : currentTask?.state === "failed"
                          ? "Retry Ingest"
                          : "Ingest Paper"}
                    </button>
                  </div>
                </div>

                {selectedDocument ? (
                  <div className="selected-paper-card">
                    <div className="selected-paper-header">
                      <div>
                        <p className="section-kicker">Selected Paper</p>
                        <h3>{selectedDocument.title}</h3>
                      </div>
                      <StatusBadge state={selectedDocumentState} />
                    </div>
                    <div className="info-grid">
                      <article className="info-card">
                        <span className="info-label">Source File</span>
                        <strong>{selectedDocument.file_name}</strong>
                        <p>{selectedDocument.path}</p>
                      </article>
                      <article className="info-card">
                        <span className="info-label">Last Modified</span>
                        <strong>{formatDate(selectedDocument.modified_at)}</strong>
                        <p>{selectedDocument.ingested ? "Indexed for retrieval" : "Waiting to be indexed"}</p>
                      </article>
                      <article className="info-card">
                        <span className="info-label">Next Step</span>
                        <strong>{paperView === "reader" ? "Continue reading" : "Open and annotate"}</strong>
                        <p>Use the actions above to read, inspect figures, or queue ingestion.</p>
                      </article>
                    </div>
                    <div className="desk-preview-card">
                      <strong>Why this layout</strong>
                      <p>
                        Visible actions replace the old right-click-only flow, while the current paper
                        stays pinned as the center of the workspace.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="empty-state-card">
                    <strong>No paper selected</strong>
                    <p>Scan papers and select one from the left column to start reading or asking the assistant.</p>
                  </div>
                )}
              </section>
            )}
          </section>

          <aside className="workspace-panel desk-context">
            <div className="desk-context-stack">
              <section className="panel-section context-card">
                <div className="section-heading">
                  <div>
                    <p className="section-kicker">Current Scope</p>
                    <h2>Paper Context</h2>
                  </div>
                  <StatusBadge state={selectedDocumentState} />
                </div>
                {selectedDocument ? (
                  <>
                    <p className="context-title">{selectedDocument.title}</p>
                    <p className="context-copy">{selectedDocument.path}</p>
                    <p className="context-copy">
                      AI replies in this workspace should be understood as grounded in the selected paper
                      when available.
                    </p>
                  </>
                ) : (
                  <p className="context-copy">
                    Select a paper to pin reading context for notes, citations, and grounded assistant answers.
                  </p>
                )}
              </section>

              <section className="panel-section memo-panel">
                <div className="section-heading">
                  <div>
                    <p className="section-kicker">Reading Notes</p>
                    <h2>Paper Memo</h2>
                  </div>
                  <span className="chip">Quick Recall</span>
                </div>
                <textarea
                  className="input textarea note-textarea"
                  rows={10}
                  value={selectedNote}
                  onChange={(event) => updateSelectedNote(event.target.value)}
                  placeholder="Capture the contribution, methodology, surprises, or reproduction notes for this paper."
                  disabled={!selectedDocument}
                />
              </section>

              <section className="panel-section assistant-panel">
                <div className="section-heading">
                  <div>
                    <p className="section-kicker">Grounded Assistant</p>
                    <h2>Paper Copilot</h2>
                  </div>
                  <span className="chip">Shared AI</span>
                </div>
                <PaperLabChatPanel
                  projectId={projectId}
                  title="Paper Workspace Assistant"
                  description="Same AI capability as the console workspace, but scoped around the active paper and reading session."
                  placeholder="Ask for explanations, method breakdowns, figure interpretation, or reproduction hints..."
                  contextLabel={
                    selectedDocument
                      ? `Active paper: ${selectedDocument.title}`
                      : "Scope: library without pinned paper"
                  }
                  compact
                />
              </section>

              <section className="panel-section task-section">
                <div className="section-heading">
                  <div>
                    <p className="section-kicker">Ingestion Monitoring</p>
                    <h2>Task History</h2>
                  </div>
                  <span className="chip">{filteredTasks.length}</span>
                </div>
                <div className="task-filter-row">
                  {(["all", "active", "failed", "completed"] as const).map((filter) => (
                    <button
                      key={filter}
                      className={`task-filter-button ${taskFilter === filter ? "active" : ""}`}
                      onClick={() => setTaskFilter(filter)}
                    >
                      {capitalize(filter)}
                    </button>
                  ))}
                </div>
                {filteredTasks.length === 0 ? (
                  <div className="empty-state-card compact">
                    <strong>No ingestion tasks yet</strong>
                    <p>Queue a paper to see recent ingestion activity here.</p>
                  </div>
                ) : (
                  <div className="task-list">
                    {filteredTasks.map((task) => (
                      <article className="task-card" key={task.task_id}>
                        <div className="task-head">
                          <strong>{task.result?.status || task.state}</strong>
                          <StatusBadge state={task.state} />
                        </div>
                        <p className="task-path">{task.path}</p>
                        <p className="task-meta">
                          {task.result?.message || task.error_message || "Waiting for execution."}
                        </p>
                        <p className="task-meta">Created: {formatDate(task.created_at)}</p>
                        {task.started_at ? (
                          <p className="task-meta">Started: {formatDate(task.started_at)}</p>
                        ) : null}
                        {task.finished_at ? (
                          <p className="task-meta">Finished: {formatDate(task.finished_at)}</p>
                        ) : null}
                        {task.error_code ? (
                          <p className="task-meta">
                            {task.error_code}
                            {task.retryable ? " · retryable" : ""}
                            {task.timed_out ? " · timed out" : ""}
                          </p>
                        ) : null}
                        {task.state === "failed" && task.retryable ? (
                          <button className="button subtle task-retry-button" onClick={() => void retryTask(task)}>
                            Retry Task
                          </button>
                        ) : null}
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </aside>
        </section>
      ) : (
        <section
          className="ai-workspace"
          id="ai-workspace-panel"
          role="tabpanel"
          aria-labelledby="ai-workspace-tab"
        >
          <aside className="workspace-panel ai-sidebar">
            <section className="panel-section">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Workspace Scope</p>
                  <h2>Project Lens</h2>
                </div>
                <span className="chip">Same AI</span>
              </div>
              <div className="info-grid single-column">
                <article className="info-card">
                  <span className="info-label">Project Id</span>
                  <strong>{projectId}</strong>
                  <p>Shared assistant runtime and retrieval scope</p>
                </article>
                <article className="info-card">
                  <span className="info-label">Pinned Paper</span>
                  <strong>{selectedDocument?.title || "None selected"}</strong>
                  <p>Return to Paper Workspace when you need side-by-side reading.</p>
                </article>
                <article className="info-card">
                  <span className="info-label">Use Case</span>
                  <strong>Analysis and reproduction planning</strong>
                  <p>Best for cross-paper reasoning, open-ended planning, and longer task breakdowns.</p>
                </article>
              </div>
            </section>
          </aside>

          <section className="workspace-panel ai-main">
            <div className="workspace-toolbar">
              <div>
                <p className="section-kicker">AI Workspace</p>
                <h2>AI Research Console</h2>
                <p className="toolbar-copy">
                  The same assistant capability, now in a conversation-first layout without the PDF
                  reader.
                </p>
              </div>
              <div className="button-row">
                <button className="button subtle" onClick={() => setWorkspace("paper")}>
                  Return to Paper Workspace
                </button>
                {selectedDocument ? (
                  <button className="button primary" onClick={() => openReader(selectedDocument)}>
                    Open Selected Paper
                  </button>
                ) : null}
              </div>
            </div>

            <PaperLabChatPanel
              projectId={projectId}
              title="AI Workspace Assistant"
              description="Use the same grounded assistant for analysis, comparison, reproduction planning, and broader research tasks."
              placeholder="Ask for synthesis, comparison, implementation planning, or reproduction strategies..."
              contextLabel={
                selectedDocument
                  ? `Pinned context available: ${selectedDocument.title}`
                  : "Scope: whole project workspace"
              }
            />
          </section>

          <aside className="workspace-panel ai-context">
            <div className="ai-context-stack">
              <section className="panel-section">
                <div className="section-heading">
                  <div>
                    <p className="section-kicker">Execution Context</p>
                    <h2>Research Notes</h2>
                  </div>
                  <span className="chip">Console Sidecar</span>
                </div>
                <div className="info-grid single-column">
                  <article className="info-card">
                    <span className="info-label">Recommended Uses</span>
                    <strong>Explain, compare, reproduce</strong>
                    <p>Use this workspace when the conversation should stay central and the PDF should not dominate the layout.</p>
                  </article>
                  <article className="info-card">
                    <span className="info-label">Evidence Flow</span>
                    <strong>Shared with Paper Workspace</strong>
                    <p>Citations, evidence counts, and project scope still come from the same assistant runtime.</p>
                  </article>
                  <article className="info-card">
                    <span className="info-label">Hand-off</span>
                    <strong>Reader remains one click away</strong>
                    <p>When the assistant points to a specific paper, move back to the Paper Workspace to read and annotate in place.</p>
                  </article>
                </div>
              </section>
            </div>
          </aside>
        </section>
      )}

      {contextMenu.visible && contextMenu.document ? (
        <div
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <button className="context-menu-item" onClick={() => openReader(contextMenu.document!)}>
            Open Reader
          </button>
          <button className="context-menu-item" onClick={() => void loadDocumentImages(contextMenu.document!)}>
            Open Figure Gallery
          </button>
          <button
            className="context-menu-item"
            onClick={() => void queueIngestion(contextMenu.document!)}
            disabled={
              ingestingDocumentId === contextMenu.document.id ||
              isTaskActive(getTaskForDocument(contextMenu.document, taskByPath))
            }
          >
            {ingestingDocumentId === contextMenu.document.id
              ? "Queueing..."
              : getDocumentActionLabel(contextMenu.document, taskByPath)}
          </button>
        </div>
      ) : null}

      {galleryOpen ? (
        <div className="modal-backdrop" onClick={closeGallery}>
          <section className="modal-panel" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="section-kicker">Figure Gallery</p>
                <h2>{galleryDocument?.title || "Figure Gallery"}</h2>
                <p className="toolbar-copy">{galleryDocument?.path}</p>
              </div>
              <button className="button subtle" onClick={closeGallery}>
                Close
              </button>
            </header>

            {loadingImages ? <p className="loading-copy">Loading extracted visual assets...</p> : null}
            {!loadingImages && documentImages.length === 0 ? (
              <div className="empty-state-card">
                <strong>No extracted figures</strong>
                <p>No body figures were extracted from this paper.</p>
              </div>
            ) : null}

            <div className="gallery-grid">
              {documentImages.map((image) => (
                <article className="gallery-card" key={image.id}>
                  {image.preview_url ? (
                    <img
                      className="gallery-image"
                      src={image.preview_url}
                      alt={image.asset_label || image.file_name}
                      loading="lazy"
                    />
                  ) : (
                    <div className="gallery-image empty-image">Preview unavailable</div>
                  )}
                  <div className="gallery-copy">
                    <strong>{image.figure_label || image.asset_label || `Page ${image.page_number}`}</strong>
                    <p>{image.summary || image.caption || "No extracted summary."}</p>
                    <small>{image.caption || `${image.asset_type} · page ${image.page_number}`}</small>
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

function StatusBadge({ state }: { state: string }) {
  return <span className={`status-badge state-${state.toLowerCase()}`}>{humanizeState(state)}</span>;
}

function renderTaskState(
  document: ScannedDocument,
  taskByPath: Record<string, IngestionTaskSummary>,
) {
  const task = taskByPath[document.path];
  if (!task) {
    return document.ingested ? "Indexed" : "Pending";
  }
  return task.state;
}

function getTaskForDocument(
  document: ScannedDocument,
  taskByPath: Record<string, IngestionTaskSummary>,
) {
  return taskByPath[document.path];
}

function isTaskActive(task?: IngestionTaskSummary | null) {
  return task?.state === "queued" || task?.state === "running";
}

function getDocumentActionLabel(
  document: ScannedDocument,
  taskByPath: Record<string, IngestionTaskSummary>,
) {
  const task = getTaskForDocument(document, taskByPath);
  if (document.ingested) {
    return "Re-ingest Paper";
  }
  if (task?.state === "failed") {
    return "Retry Ingest";
  }
  if (isTaskActive(task)) {
    return "Ingesting...";
  }
  return "Ingest Paper";
}

function formatDate(value?: string | null) {
  if (!value) {
    return "Unknown";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function humanizeState(value: string) {
  return value.replace(/_/g, " ");
}

export default App;
