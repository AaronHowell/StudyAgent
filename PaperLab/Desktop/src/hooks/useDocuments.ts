import { useCallback, useEffect, useState } from "react";
import type { ScannedDocument } from "../types";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export type IngestionTaskSummary = {
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

export function useDocuments() {
  const [documents, setDocuments] = useState<ScannedDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [taskByPath, setTaskByPath] = useState<Record<string, IngestionTaskSummary>>({});
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  const [batchIngesting, setBatchIngesting] = useState(false);

  const refreshTasks = useCallback(async () => {
    try {
      const response = await fetch(`${apiBase}/documents/ingest`);
      if (!response.ok) return;
      const tasks = (await response.json()) as IngestionTaskSummary[];
      setTaskByPath(() => {
        const next: Record<string, IngestionTaskSummary> = {};
        for (const task of tasks) next[task.path] = task;
        return next;
      });
      setDocuments((current) =>
        current.map((doc) => {
          const task = tasks.find((t) => t.path === doc.path);
          if (task?.state === "completed") return { ...doc, ingested: true };
          return doc;
        }),
      );
    } catch { /* keep current */ }
  }, []);

  const scan = useCallback(async (rootPath: string, projectId: string) => {
    if (!rootPath) { setError("请先选择项目目录。"); return; }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBase}/documents/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_path: rootPath, project_id: projectId }),
      });
      if (!response.ok) throw new Error(await response.text());
      const payload = (await response.json()) as { documents: ScannedDocument[] };
      setDocuments(payload.documents);
      await refreshTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "扫描论文失败");
    } finally {
      setLoading(false);
    }
  }, [refreshTasks]);

  const ingest = useCallback(async (document: ScannedDocument, projectId: string) => {
    setIngestingId(document.id);
    setError("");
    try {
      const response = await fetch(`${apiBase}/documents/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, path: document.path }),
      });
      if (!response.ok) throw new Error(await response.text());
      const payload = (await response.json()) as { task: IngestionTaskSummary };
      setTaskByPath((current) => ({ ...current, [document.path]: payload.task }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交入库失败");
    } finally {
      setIngestingId(null);
    }
  }, []);

  const batchIngest = useCallback(async (projectId: string) => {
    const candidates = documents
      .filter((doc) => {
        const task = taskByPath[doc.path];
        return !doc.ingested && !isTaskActive(task);
      })
      .map((doc) => doc.path);
    if (candidates.length === 0) return;

    setBatchIngesting(true);
    setError("");
    try {
      const response = await fetch(`${apiBase}/documents/ingest/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, paths: candidates }),
      });
      if (!response.ok) throw new Error(await response.text());
      const payload = (await response.json()) as { tasks: IngestionTaskSummary[] };
      setTaskByPath((current) => {
        const next = { ...current };
        for (const task of payload.tasks) next[task.path] = task;
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量入库失败");
    } finally {
      setBatchIngesting(false);
    }
  }, [documents, taskByPath]);

  // Poll active tasks
  useEffect(() => {
    const hasActive = Object.values(taskByPath).some((t) => t.state === "queued" || t.state === "running");
    if (!hasActive) return;
    const timer = window.setInterval(() => { void refreshTasks(); }, 1500);
    return () => window.clearInterval(timer);
  }, [taskByPath, refreshTasks]);

  const activeTaskCount = Object.values(taskByPath).filter((t) => t.state === "queued" || t.state === "running").length;
  const completedCount = documents.filter((d) => d.ingested).length;
  const pendingCount = documents.filter((d) => {
    const task = taskByPath[d.path];
    return !d.ingested && !isTaskActive(task);
  }).length;

  return {
    documents,
    loading,
    error,
    taskByPath,
    ingestingId,
    batchIngesting,
    activeTaskCount,
    completedCount,
    pendingCount,
    scan,
    ingest,
    batchIngest,
    refreshTasks,
    setError,
  };
}

function isTaskActive(task?: IngestionTaskSummary | null) {
  return task?.state === "queued" || task?.state === "running";
}
