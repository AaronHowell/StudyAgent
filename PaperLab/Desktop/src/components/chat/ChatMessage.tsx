import { Bot, User } from "lucide-react";
import type { ChatTurn } from "../../usePaperLabStream";
import { AgentTrace } from "./AgentTrace";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { CitationList } from "./CitationList";
import { AssetSourceGrid } from "./AssetSourceGrid";

export function ChatMessage({
  turn,
  showSummary,
  onToggleTrace,
}: {
  turn: ChatTurn;
  showSummary: boolean;
  onToggleTrace: () => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="message">
        <div className="message-avatar message-avatar-user">
          <User size={14} />
        </div>
        <div className="message-content">
          <div className="message-body">{turn.content ?? ""}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="message">
      <div className="message-avatar message-avatar-assistant">
        <Bot size={14} />
      </div>
      <div className="message-content">
        <AgentTrace
          items={turn.trace_items ?? []}
          status={turn.status}
          collapsed={turn.collapsed ?? false}
          onToggle={onToggleTrace}
        />

        <div className="message-body">
          {turn.answer_text ? <MarkdownRenderer content={turn.answer_text} assetSources={turn.asset_sources ?? []} /> : null}
        </div>

        {showSummary && turn.summary ? (
          <div style={{ fontSize: 12, color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: 2 }}>
            {turn.summary.done ? <p>已完成：{turn.summary.done}</p> : null}
            {turn.summary.next ? <p>下一步：{turn.summary.next}</p> : null}
            {turn.summary.pending ? <p>未完成：{turn.summary.pending}</p> : null}
          </div>
        ) : null}

        <CitationList
          citations={turn.citations ?? []}
          assetCitations={turn.asset_citations ?? []}
        />

        <AssetSourceGrid sources={turn.asset_sources ?? []} />

        {turn.web_sources && turn.web_sources.length > 0 ? (
          <div className="citation-row">
            {turn.web_sources.map((src) => (
              <a className="citation-chip" key={src.url} href={src.url} target="_blank" rel="noreferrer">
                {src.title || src.url}
              </a>
            ))}
          </div>
        ) : null}

        {turn.tool_sources && turn.tool_sources.length > 0 ? (
          <div className="citation-row">
            {turn.tool_sources.map((src, i) =>
              src.url ? (
                <a className="citation-chip" key={`${src.url}-${i}`} href={src.url} target="_blank" rel="noreferrer">
                  {src.title || src.tool_name || "工具来源"}
                </a>
              ) : (
                <span className="citation-chip" key={`${src.title}-${i}`}>
                  {src.title || src.tool_name || "工具来源"}
                </span>
              ),
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
