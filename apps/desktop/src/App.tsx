import { useEffect, useMemo, useState } from "react";
import { StudyAgentChatPanel, buildDocumentFileUrl } from "./StudyAgentChatPanel";
import type { DocumentImage, ScannedDocument } from "./types";

type WorkspaceMode = "library" | "solo";
type CurrentView = "library" | "reader";
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
  import.meta.env.VITE_STUDY_AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";

function App() {
  const [mode, setMode] = useState<WorkspaceMode>("library");
  const [currentView, setCurrentView] = useState<CurrentView>("library");
  const [rootPath, setRootPath] = useState("C:\\Users\\Aaron_Howell\\Desktop\\postgraduate");
  const [projectId, setProjectId] = useState("frontend-project");
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [documents, setDocuments] = useState<ScannedDocument[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<ScannedDocument | null>(null);
  const [documentImages, setDocumentImages] = useState<GalleryImage[]>([]);
  const [notesByDocumentId, setNotesByDocumentId] = useState<Record<string, string>>({});
  const [aiDockOpen, setAiDockOpen] = useState(true);
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

  useEffect(() => {
    function handleWindowClick() {
      setContextMenu((current) => ({ ...current, visible: false, document: null }));
    }

    function handleEsc(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setGalleryOpen(false);
        resetGalleryImages();
      }
    }

    window.addEventListener("click", handleWindowClick);
    window.addEventListener("keydown", handleEsc);
    return () => {
      window.removeEventListener("click", handleWindowClick);
      window.removeEventListener("keydown", handleEsc);
    };
  }, [documentImages]);

  useEffect(() => {
    void refreshTaskList();
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
    const activeTasks = Object.values(taskByPath).filter(
      (task) => task.state === "queued" || task.state === "running",
    );

    if (activeTasks.length === 0) {
      return;
    }

    timer = window.setInterval(async () => {
      await refreshTaskList();
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
      resetGalleryImages();
      setCurrentView("library");
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
        const hasActiveTask = task && (task.state === "queued" || task.state === "running");
        return !document.ingested && !hasActiveTask;
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

  function openDocument(document: ScannedDocument) {
    setSelectedDocument(document);
    setCurrentView("reader");
    closeContextMenu();
  }

  function backToLibrary() {
    setCurrentView("library");
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

  function showPdfOnly(document: ScannedDocument) {
    setSelectedDocument(document);
    setCurrentView("reader");
    closeContextMenu();
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

  function openContextMenu(event: React.MouseEvent, document: ScannedDocument) {
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

  async function handleViewImages() {
    if (contextMenu.document) {
      await loadDocumentImages(contextMenu.document);
    }
  }

  function handleOpenOriginal() {
    if (contextMenu.document) {
      showPdfOnly(contextMenu.document);
    }
  }

  async function handleIngestDocument() {
    if (contextMenu.document) {
      await queueIngestion(contextMenu.document);
      closeContextMenu();
    }
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
  }

  function renderTaskState(document: ScannedDocument) {
    const task = taskByPath[document.path];
    if (!task) {
      return document.ingested ? "Indexed" : "Pending";
    }
    return task.state;
  }

  function getTaskForDocument(document: ScannedDocument) {
    return taskByPath[document.path];
  }

  function isTaskActive(task?: IngestionTaskSummary | null) {
    return task?.state === "queued" || task?.state === "running";
  }

  function getDocumentActionLabel(document: ScannedDocument) {
    const task = getTaskForDocument(document);
    if (document.ingested) {
      return "Re-ingest Document";
    }
    if (task?.state === "failed") {
      return "Retry Ingest";
    }
    if (isTaskActive(task)) {
      return "Ingesting...";
    }
    return "Ingest Document";
  }

  function getPendingDocumentCount() {
    return documents.filter((document) => {
      const task = getTaskForDocument(document);
      return !document.ingested && !isTaskActive(task);
    }).length;
  }

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

  return (
    <main
      className={`workspace ${aiDockOpen && mode === "library" ? "with-ai-dock" : "without-ai-dock"}`}
      onContextMenu={(event) => event.preventDefault()}
    >
      <div className="workspace-mode-switch">
        <button
          className={`mode-button ${mode === "library" ? "active" : ""}`}
          onClick={() => setMode("library")}
        >
          Library Mode
        </button>
        <button
          className={`mode-button ${mode === "solo" ? "active" : ""}`}
          onClick={() => setMode("solo")}
        >
          SOLO Mode
        </button>
      </div>

      {mode === "library" && aiDockOpen ? (
      <aside className="floating-ai">
        <div className="floating-header">
          <strong>StudyAgent AI</strong>
          <div className="floating-actions">
            <span className="chip">Grounded QA</span>
            <button className="icon-button" onClick={() => setAiDockOpen(false)}>
              Hide
            </button>
          </div>
        </div>
        <StudyAgentChatPanel
          projectId={projectId}
          title="Reader Copilot"
          description="Library mode keeps the PDF desk in focus while the LangGraph agent stays available for grounded questions."
          placeholder="Ask the agent to summarize, compare, or explain the indexed papers..."
          contextLabel={selectedDocument ? `Focus: ${selectedDocument.title}` : "Scope: whole library"}
          compact
        />
      </aside>
      ) : null}

      {mode === "library" && !aiDockOpen ? (
        <button className="floating-launcher" onClick={() => setAiDockOpen(true)}>
          Open AI
        </button>
      ) : null}

      {mode === "library" ? (
        <>
          {currentView === "library" ? (
            <section className="shell">
              <header className="hero">
                <div>
                  <p className="eyebrow">StudyAgent Workspace</p>
                  <h1>Research Library</h1>
                  <p className="subtext">Manage your local PDF collection, queue ingestion, and jump into reading.</p>
                </div>
                <div className="hero-grid">
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
                  <button className="button primary" onClick={scanDocuments} disabled={loadingDocuments}>
                    {loadingDocuments ? "Scanning..." : "Scan PDFs"}
                  </button>
                  <button
                    className="button subtle"
                    onClick={batchIngestPendingDocuments}
                    disabled={batchIngesting || getPendingDocumentCount() === 0}
                  >
                    {batchIngesting
                      ? "Queueing Batch..."
                      : `Batch Ingest Pending (${getPendingDocumentCount()})`}
                  </button>
                </div>
              </header>

              <section className="library-grid">
                <section className="panel table-panel">
                {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
                <div className="table-wrap">
                  <table className="document-table">
                    <thead>
                      <tr>
                        <th>Title</th>
                        <th>State</th>
                        <th>Memo</th>
                        <th>File Name</th>
                        <th>Modified</th>
                        <th>Path</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((document) => (
                        <tr
                          key={document.id}
                          className={selectedDocument?.id === document.id ? "selected" : ""}
                          onClick={() => setSelectedDocument(document)}
                          onDoubleClick={() => openDocument(document)}
                          onContextMenu={(event) => openContextMenu(event, document)}
                        >
                          <td>{document.title}</td>
                          <td>
                            <span className={`status-badge state-${renderTaskState(document).toLowerCase()}`}>
                              {renderTaskState(document)}
                            </span>
                          </td>
                          <td>{notesByDocumentId[document.id] || "No memo yet."}</td>
                          <td>{document.file_name}</td>
                          <td>{new Date(document.modified_at).toLocaleString()}</td>
                          <td className="path-cell">{document.path}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="hint">Double click opens the reader. Right click opens document actions.</p>
                </section>

                <aside className="panel task-panel">
                  <div className="section-head">
                    <h2>Ingestion Tasks</h2>
                    <span className="chip">{filteredTasks.length}</span>
                  </div>
                  <div className="task-filter-row">
                    <button
                      className={`task-filter-button ${taskFilter === "all" ? "active" : ""}`}
                      onClick={() => setTaskFilter("all")}
                    >
                      All
                    </button>
                    <button
                      className={`task-filter-button ${taskFilter === "active" ? "active" : ""}`}
                      onClick={() => setTaskFilter("active")}
                    >
                      Active
                    </button>
                    <button
                      className={`task-filter-button ${taskFilter === "failed" ? "active" : ""}`}
                      onClick={() => setTaskFilter("failed")}
                    >
                      Failed
                    </button>
                    <button
                      className={`task-filter-button ${taskFilter === "completed" ? "active" : ""}`}
                      onClick={() => setTaskFilter("completed")}
                    >
                      Completed
                    </button>
                  </div>
                  {filteredTasks.length === 0 ? (
                    <p className="task-empty">No ingestion tasks yet.</p>
                  ) : (
                    <div className="task-list">
                      {filteredTasks.map((task) => (
                        <article className="task-card" key={task.task_id}>
                          <div className="task-head">
                            <strong>{task.result?.status || task.state}</strong>
                            <span className={`status-badge state-${task.state.toLowerCase()}`}>{task.state}</span>
                          </div>
                          <p className="task-path">{task.path}</p>
                          <p className="task-meta">
                            {task.result?.message || task.error_message || "Waiting for execution."}
                          </p>
                          {task.error_code ? (
                            <small className="task-meta">
                              {task.error_code}
                              {task.retryable ? " · retryable" : ""}
                              {task.timed_out ? " · timed out" : ""}
                            </small>
                          ) : null}
                          {task.error_type ? <small className="task-meta">Type: {task.error_type}</small> : null}
                          {task.started_at ? (
                            <small className="task-meta">
                              Started: {new Date(task.started_at).toLocaleString()}
                            </small>
                          ) : null}
                          {task.finished_at ? (
                            <small className="task-meta">
                              Finished: {new Date(task.finished_at).toLocaleString()}
                            </small>
                          ) : null}
                          <small className="task-meta">
                            Created: {new Date(task.created_at).toLocaleString()}
                          </small>
                          {task.state === "failed" && task.retryable ? (
                            <button className="button subtle task-retry-button" onClick={() => void retryTask(task)}>
                              Retry Task
                            </button>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  )}
                </aside>
              </section>
            </section>
          ) : (
            <section className="reader-page">
              <header className="hero reader-hero">
                <div>
                  <p className="eyebrow">StudyAgent Reader</p>
                  <h1>{selectedDocument?.title || "Reader"}</h1>
                  <p className="subtext">{selectedDocument?.path}</p>
                </div>
                <div className="reader-actions">
                  <button className="button subtle" onClick={backToLibrary}>
                    Back To Library
                  </button>
                  {selectedDocument ? (
                    <button className="button primary" onClick={() => loadDocumentImages(selectedDocument)}>
                      Open Figure Gallery
                    </button>
                  ) : null}
                </div>
              </header>

              <section className="reader-shell">
                <div className="panel pdf-panel">
                  {selectedPdfUrl ? (
                    <iframe src={selectedPdfUrl} className="pdf-viewer" title="PDF Viewer" />
                  ) : (
                    <div className="empty-state">No document selected.</div>
                  )}
                </div>
                <aside className="panel note-panel">
                  <div className="section-head">
                    <h2>Paper Memo</h2>
                    <span className="chip">Quick Recall</span>
                  </div>
                  <textarea
                    className="input textarea note-textarea"
                    rows={10}
                    value={selectedNote}
                    onChange={(event) => updateSelectedNote(event.target.value)}
                    placeholder="Write a short memo here after reading this paper."
                  />
                  <div className="reader-ai-hint">
                    <strong>AI Panel</strong>
                    <p>Use the right-side LangGraph chat dock for grounded questions while reading.</p>
                    {!aiDockOpen ? (
                      <button className="button subtle" onClick={() => setAiDockOpen(true)}>
                        Open AI Dock
                      </button>
                    ) : null}
                  </div>
                </aside>
              </section>
            </section>
          )}

          {contextMenu.visible && contextMenu.document ? (
            <div
              className="context-menu"
              style={{ left: contextMenu.x, top: contextMenu.y }}
              onClick={(event) => event.stopPropagation()}
            >
              <button className="context-menu-item" onClick={handleOpenOriginal}>
                Open Original PDF
              </button>
              <button className="context-menu-item" onClick={handleViewImages}>
                Open Figure Gallery
              </button>
              <button
                className="context-menu-item"
                onClick={handleIngestDocument}
                disabled={
                  ingestingDocumentId === contextMenu.document.id ||
                  isTaskActive(getTaskForDocument(contextMenu.document))
                }
              >
                {ingestingDocumentId === contextMenu.document.id
                  ? "Queueing..."
                  : getDocumentActionLabel(contextMenu.document)}
              </button>
            </div>
          ) : null}

          {galleryOpen ? (
            <div className="modal-backdrop" onClick={closeGallery}>
              <section className="modal-panel" onClick={(event) => event.stopPropagation()}>
                <header className="modal-header">
                  <div>
                    <p className="eyebrow">StudyAgent Gallery</p>
                    <h2>{galleryDocument?.title || "Figure Gallery"}</h2>
                    <p className="subtext">{galleryDocument?.path}</p>
                  </div>
                  <button className="button subtle" onClick={closeGallery}>
                    Close
                  </button>
                </header>

                {loadingImages ? <p className="loading-copy">Loading extracted visual assets...</p> : null}
                {!loadingImages && documentImages.length === 0 ? (
                  <div className="empty-gallery">No body figures were extracted from this paper.</div>
                ) : null}

                <div className="gallery-grid">
                  {documentImages.map((image) => (
                    <article className="gallery-card" key={image.id}>
                      {image.preview_url ? (
                        <img className="gallery-image" src={image.preview_url} alt={image.asset_label || image.file_name} loading="lazy" />
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
        </>
      ) : (
        <section className="shell solo-shell">
          <header className="hero">
            <div>
              <p className="eyebrow">SOLO Mode</p>
              <h1>Agent Conversation Console</h1>
              <p className="subtext">
                This mode will be the landing zone for LangGraph agent chat. The library and reader context can be
                shared into the conversation panel later.
              </p>
            </div>
          </header>

          <section className="solo-grid">
            <div className="panel solo-card">
              <StudyAgentChatPanel
                projectId={projectId}
                title="SOLO Conversation"
                description="Official LangGraph stream and assistant-ui runtime for the main agent workspace."
                placeholder="Ask a grounded question and stream the answer..."
                contextLabel={selectedDocument ? `Selected: ${selectedDocument.title}` : "No document pinned"}
              />
            </div>
            <div className="panel solo-card">
              <h2>Shared Context</h2>
              <p>Current selected document: {selectedDocument?.title || "None"}</p>
              <p>Scanned documents: {documents.length}</p>
              <p>Queued ingestion tasks: {Object.keys(taskByPath).length}</p>
              <p>FastAPI capabilities stay available for scan, ingest, file serving, and retrieval debugging.</p>
            </div>
          </section>
        </section>
      )}
    </main>
  );
}

export default App;
