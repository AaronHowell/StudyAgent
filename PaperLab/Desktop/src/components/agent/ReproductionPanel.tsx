import { useState } from "react";
import { Play, RefreshCw, Pause, XCircle, ChevronDown, ChevronRight } from "lucide-react";
import type { ReproductionRun } from "../../types";
import { StatusBadge } from "../common/StatusBadge";

const TASK_ORDER = [
  "understand_paper",
  "extract_method",
  "inspect_figures",
  "design_reproduction",
  "create_project",
  "run_experiment",
  "analyze_results",
  "write_report",
];

const TASK_LABELS: Record<string, string> = {
  understand_paper: "理解论文",
  extract_method: "提取方法",
  inspect_figures: "检查图表",
  design_reproduction: "设计复现方案",
  create_project: "创建项目文件",
  run_experiment: "运行实验",
  analyze_results: "分析结果",
  write_report: "撰写报告",
};

export function ReproductionPanel({
  run,
  loading,
  objective,
  onObjectiveChange,
  onStart,
  onRefresh,
  onPause,
  onResume,
  onCancel,
  hasDocument,
}: {
  run: ReproductionRun | null;
  loading: boolean;
  objective: string;
  onObjectiveChange: (v: string) => void;
  onStart: () => void;
  onRefresh: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  hasDocument: boolean;
}) {
  const [expanded, setExpanded] = useState(true);

  const tasks = run?.tasks ? Object.values(run.tasks) : [];
  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const progress = tasks.length > 0 ? (completedCount / tasks.length) * 100 : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: 16, borderBottom: "1px solid var(--border)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <button
          style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", padding: 0 }}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span style={{ fontSize: 13, fontWeight: 600 }}>论文复现</span>
          {run ? <StatusBadge state={run.status} /> : null}
        </button>
        {run ? (
          <button className="btn btn-ghost btn-sm" onClick={onRefresh}>
            <RefreshCw size={12} />
          </button>
        ) : null}
      </div>

      {expanded ? (
        <>
          {/* Objective input */}
          <div className="field">
            <span className="field-label">复现目标</span>
            <input className="input" value={objective} onChange={(e) => onObjectiveChange(e.target.value)} />
          </div>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 6 }}>
            {!run ? (
              <button className="btn btn-primary btn-sm" onClick={onStart} disabled={loading || !hasDocument}>
                <Play size={12} />
                {loading ? "启动中..." : "启动复现"}
              </button>
            ) : (
              <>
                {run.status === "running" ? (
                  <button className="btn btn-sm" onClick={onPause}>
                    <Pause size={12} /> 暂停
                  </button>
                ) : run.status === "paused" ? (
                  <button className="btn btn-primary btn-sm" onClick={onResume}>
                    <Play size={12} /> 恢复
                  </button>
                ) : null}
                {run.status !== "completed" && run.status !== "cancelled" ? (
                  <button className="btn btn-sm" onClick={onCancel} style={{ color: "var(--danger)" }}>
                    <XCircle size={12} /> 取消
                  </button>
                ) : null}
              </>
            )}
          </div>

          {/* Progress bar */}
          {run && tasks.length > 0 ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)", marginBottom: 4 }}>
                <span>进度</span>
                <span>{completedCount} / {tasks.length}</span>
              </div>
              <div className="progress-bar">
                <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>
          ) : null}

          {/* Task list */}
          {run && tasks.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {TASK_ORDER.map((taskId) => {
                const task = tasks.find((t) => t.task_type === taskId || t.title?.includes(taskId));
                if (!task) return null;
                return (
                  <div key={task.task_id} className={`task-node ${task.status}`} style={{ padding: "8px 12px" }}>
                    <div className="task-node-info">
                      <div className="task-node-title">{TASK_LABELS[task.task_type] || task.title}</div>
                      <div className="task-node-meta">{task.assigned_to || task.task_type}</div>
                    </div>
                    <StatusBadge state={task.status} />
                  </div>
                );
              })}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
