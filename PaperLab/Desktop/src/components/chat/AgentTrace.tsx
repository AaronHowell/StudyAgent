import { useState } from "react";
import { ChevronDown, Search, Code, FileText, Globe, Wrench, Brain } from "lucide-react";
import type { ChatTraceItem } from "../../usePaperLabStream";

const TRACE_ICONS: Record<string, typeof Brain> = {
  tool_call: Wrench,
  tool_result: FileText,
  search: Search,
  code: Code,
  web: Globe,
};

function traceItemLabel(item: ChatTraceItem): string {
  if (item.kind === "tool_call") return item.title || "工具调用";
  if (item.kind === "tool_result") return item.title || "工具结果";
  return item.title || "思考";
}

export function AgentTrace({
  items,
  status,
  collapsed,
  onToggle,
}: {
  items: ChatTraceItem[];
  status?: string;
  collapsed: boolean;
  onToggle: () => void;
}) {
  if (items.length === 0) return null;

  const label = status === "streaming" ? "思考中" : collapsed ? "已完成思考" : "收起思考";
  const Icon = status === "streaming" ? Brain : ChevronDown;

  return (
    <div className="trace-section">
      <button
        className={`trace-toggle ${status === "streaming" ? "streaming" : ""}`}
        onClick={onToggle}
      >
        <Icon size={14} />
        {label}
        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>({items.length})</span>
      </button>
      {!collapsed ? (
        <div className="trace-panel">
          {items.map((item) => (
            <TraceItemRow key={item.id} item={item} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TraceItemRow({ item }: { item: ChatTraceItem }) {
  const Icon = TRACE_ICONS[item.kind] || Brain;

  return (
    <div className={`trace-item ${item.kind}`}>
      <div className="trace-item-head">
        <Icon size={14} />
        <span>{traceItemLabel(item)}</span>
      </div>
      <div className="trace-item-body">{item.text}</div>
    </div>
  );
}
