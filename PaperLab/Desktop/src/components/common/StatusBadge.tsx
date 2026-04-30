const STATE_LABELS: Record<string, string> = {
  indexed: "已入库",
  pending: "待入库",
  queued: "排队中",
  running: "进行中",
  failed: "失败",
  completed: "完成",
  created: "已创建",
  paused: "已暂停",
  cancelled: "已取消",
  blocked: "阻塞",
};

const STATE_STYLES: Record<string, string> = {
  indexed: "badge-success",
  completed: "badge-success",
  pending: "badge-neutral",
  queued: "badge-warning",
  running: "badge-info",
  failed: "badge-danger",
};

export function StatusBadge({ state }: { state: string }) {
  const normalized = state.toLowerCase().replace(/\s+/g, "-");
  const style = STATE_STYLES[normalized] || "badge-neutral";
  return <span className={`badge ${style}`}>{STATE_LABELS[normalized] || state}</span>;
}
