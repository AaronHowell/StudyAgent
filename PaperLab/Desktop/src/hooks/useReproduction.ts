import { useCallback, useState } from "react";
import type { ReproductionRun } from "../types";

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function useReproduction() {
  const [run, setRun] = useState<ReproductionRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async (runId?: string) => {
    const id = runId || run?.run_id;
    if (!id) return;
    const response = await fetch(`${apiBase}/runs/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(await response.text());
    setRun((await response.json()) as ReproductionRun);
  }, [run?.run_id]);

  const start = useCallback(async (projectId: string, objective: string, paperIds: string[]) => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${apiBase}/runs/reproduce`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          objective,
          paper_ids: paperIds,
          permission_mode: "manual",
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const created = (await response.json()) as { run_id: string };
      await refresh(created.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动复现失败");
    } finally {
      setLoading(false);
    }
  }, [refresh]);

  const pause = useCallback(async () => {
    if (!run?.run_id) return;
    await fetch(`${apiBase}/runs/${run.run_id}/pause`, { method: "POST" });
    await refresh();
  }, [run?.run_id, refresh]);

  const resume = useCallback(async () => {
    if (!run?.run_id) return;
    await fetch(`${apiBase}/runs/${run.run_id}/resume`, { method: "POST" });
    await refresh();
  }, [run?.run_id, refresh]);

  const cancel = useCallback(async () => {
    if (!run?.run_id) return;
    await fetch(`${apiBase}/runs/${run.run_id}/cancel`, { method: "POST" });
    await refresh();
  }, [run?.run_id, refresh]);

  return { run, loading, error, start, refresh, pause, resume, cancel, setError };
}
