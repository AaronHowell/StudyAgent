import { Plus, Trash2 } from "lucide-react";

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
  onDelete,
}: {
  threads: ThreadSummary[];
  activeThreadId: string;
  onSelect: (thread: ThreadSummary) => void;
  onNew: () => void;
  onDelete: (thread: ThreadSummary) => void;
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
          <div
            key={thread.id}
            className={`thread-item ${thread.id === activeThreadId ? "active" : ""}`}
            style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}
          >
            <button
              className="thread-item-select"
              onClick={() => onSelect(thread)}
              style={{ flex: 1, minWidth: 0, background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", display: "flex", flexDirection: "column", gap: 2 }}
            >
              <span className="thread-item-title">{thread.title}</span>
              <span className="thread-item-time">{formatTime(thread.updatedAt)}</span>
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(thread);
              }}
              title="删除对话"
              style={{ flexShrink: 0, padding: "2px 4px" }}
            >
              <Trash2 size={12} />
            </button>
          </div>
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
