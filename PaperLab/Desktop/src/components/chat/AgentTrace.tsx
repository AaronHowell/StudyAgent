import { useState } from "react";
import { ChevronDown, Search, Code, FileText, Globe, Wrench, Brain, Plug, Package } from "lucide-react";
import type { ChatTraceItem } from "../../usePaperLabStream";

const TRACE_ICONS: Record<string, typeof Brain> = {
  tool_call: Wrench,
  tool_result: FileText,
  search: Search,
  code: Code,
  web: Globe,
  mcp: Plug,
};

const LOW_SIGNAL_TRACE_TITLES = new Set([
  "guidance_gate_pre_route",
  "guidance_gate_post_route",
  "guidance_gate_pre_assess",
  "main_route_complete",
  "parallel_specialists_complete",
  "assess_complete",
]);

function traceItemLabel(item: ChatTraceItem): string {
  if (item.kind === "tool_call") return item.title || "工具调用";
  if (item.kind === "tool_result") return item.title || "工具结果";
  return item.title || "思考";
}

function isLowSignalTraceItem(item: ChatTraceItem): boolean {
  if (item.kind !== "reasoning") return false;
  if (LOW_SIGNAL_TRACE_TITLES.has(item.title)) return true;
  const text = item.text.trim();
  return (
    text.startsWith("Loop checkpoint reached at ") ||
    text === "Parallel specialist execution finished." ||
    text.startsWith("MainRoute prepared ") ||
    text.startsWith("Assess requested another routing iteration")
  );
}

function traceItemCategory(item: ChatTraceItem): string {
  const title = item.title.trim();
  if (title === "长期记忆检索" || title === "长期记忆写入") return "memory";
  if (title === "retrieval_agent" || title === "检索思路" || title.includes("检索")) return "retrieval";
  if (item.kind === "tool_call" && title.includes("::")) return "mcp";
  if (item.kind === "tool_result" && title.includes("::")) return "mcp";
  return "default";
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
  const visibleItems = items.filter((item) => !isLowSignalTraceItem(item));
  if (visibleItems.length === 0) return null;

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
        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>({visibleItems.length})</span>
      </button>
      {!collapsed ? (
        <div className="trace-panel">
          {visibleItems.map((item) => (
            <TraceItemRow key={item.id} item={item} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

type RecommendedTool = {
  name: string;
  description?: string;
  why_selected?: string;
  kind?: string;
};

function ToolSearchResultCard({ item }: { item: ChatTraceItem }) {
  const tools = (item.metadata?.recommended_tools as RecommendedTool[]) ?? [];
  return (
    <div className="trace-item tool_result trace-item-tool-search">
      <div className="trace-item-head">
        <Package size={14} />
        <span>{item.title || "工具发现"}</span>
      </div>
      {tools.length > 0 ? (
        <div className="tool-search-list">
          {tools.map((tool) => (
            <div key={tool.name} className="tool-search-card">
              <div className="tool-search-card-header">
                <Wrench size={12} />
                <span className="tool-search-name">{tool.name}</span>
                {tool.kind ? <span className="tool-search-kind">{tool.kind}</span> : null}
              </div>
              {tool.description ? <div className="tool-search-desc">{tool.description}</div> : null}
              {tool.why_selected ? <div className="tool-search-reason">{tool.why_selected}</div> : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="trace-item-body">{item.text}</div>
      )}
    </div>
  );
}

function TraceItemRow({ item }: { item: ChatTraceItem }) {
  const Icon = TRACE_ICONS[item.kind] || Brain;
  const category = traceItemCategory(item);
  const isToolSearch = item.title === "工具发现" || item.metadata?.recommended_tools;

  if (isToolSearch) {
    return <ToolSearchResultCard item={item} />;
  }

  return (
    <div className={`trace-item ${item.kind} ${category !== "default" ? `trace-item-${category}` : ""}`}>
      <div className="trace-item-head">
        <Icon size={14} />
        <span>{traceItemLabel(item)}</span>
      </div>
      <div className="trace-item-body">{item.text}</div>
    </div>
  );
}
