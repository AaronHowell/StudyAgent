import { Plus } from "lucide-react";

type ThreadSummary = {
  id: string;
  title: string;
  projectId: string;
  updatedAt: string;
};

export function ThreadSidebar({
  threads,
  activeThreadId,
  onSelect,
  onNew,
}: {
  threads: ThreadSummary[];
  activeThreadId: string;
  onSelect: (thread: ThreadSummary) => void;
  onNew: () => void;
}) {
  return (
    <div className="thread-sidebar">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 6px", marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-tertiary)" }}>
          对话历史
        </span>
        <button className="btn btn-ghost btn-sm" onClick={onNew} title="新对话">
          <Plus size={14} />
        </button>
      </div>

      {threads.length === 0 ? (
        <div style={{ padding: "12px 8px", fontSize: 12, color: "var(--text-tertiary)" }}>暂无对话</div>
      ) : (
        threads.map((thread) => (
          <button
            key={thread.id}
            className={`thread-item ${thread.id === activeThreadId ? "active" : ""}`}
            onClick={() => onSelect(thread)}
          >
            <span className="thread-item-title">{thread.title}</span>
            <span className="thread-item-time">{formatTime(thread.updatedAt)}</span>
          </button>
        ))
      )}
    </div>
  );
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
