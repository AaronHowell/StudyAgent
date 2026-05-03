import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  type ChatTraceItem,
  type ChatTurn,
  type CitationRecord,
  type InterruptPayload,
  type MessageSummary,
  usePaperLabStream,
} from "./usePaperLabStream";
import type { ChatSessionSummary } from "./types";
import { MarkdownRenderer } from "./components/chat/MarkdownRenderer";

type LoopInterruptValue = {
  phase?: string;
  question?: string;
};

type ChatThreadSummary = {
  id: string;
  title: string;
  projectId: string;
  updatedAt: string;
};

type PaperLabChatPanelProps = {
  projectId: string;
  title: string;
  description?: string;
  placeholder: string;
  contextLabel?: string;
  compact?: boolean;
  showThreadSidebar?: boolean;
};

const apiBase =
  import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function PaperLabChatPanel({
  projectId,
  title,
  description = "",
  placeholder,
  contextLabel = "",
  compact = false,
  showThreadSidebar = false,
}: PaperLabChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [interventionDraft, setInterventionDraft] = useState("");
  const [showSummaries, setShowSummaries] = useState(false);
  const [serverThreads, setServerThreads] = useState<ChatThreadSummary[]>([]);
  const submitLockRef = useRef(false);
  const stream = usePaperLabStream<LoopInterruptValue>({
    apiBaseUrl: apiBase,
  });

  const groupedThreads = useMemo(() => groupThreadsByProject(serverThreads), [serverThreads]);

  useEffect(() => {
    let cancelled = false;

    void stream
      .listSessions(projectId)
      .then((sessions) => {
        if (cancelled) {
          return;
        }
        const nextThreads = sessions.map(toThreadSummary);
        setServerThreads(nextThreads);

        const latestThread = nextThreads[0];
        if (!latestThread) {
          stream.resetThread();
          return;
        }

        void stream.restoreSession({ projectId, threadId: latestThread.id }).catch(() => {
          if (!cancelled) {
            stream.resetThread(latestThread.id);
          }
        });
      })
      .catch(() => {
        if (!cancelled) {
          setServerThreads([]);
          stream.resetThread();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, stream.listSessions, stream.restoreSession, stream.resetThread]);

  async function handleSendMessage() {
    if (submitLockRef.current || stream.isLoading) {
      return;
    }

    const text = draft.trim();
    if (!text) {
      return;
    }

    const threadId = stream.threadId;
    upsertThreadSummary({
      id: threadId,
      title: buildThreadTitle(text),
      projectId,
      updatedAt: new Date().toISOString(),
    });

    setDraft("");
    submitLockRef.current = true;

    try {
      await stream.submit(
        {
          messages: [
            {
              type: "human",
              content: text,
            },
          ],
        },
        {
          projectId,
          optimisticTurns: [
            {
              id: `local-user-${Date.now()}`,
              role: "user",
              content: text,
              created_at: new Date().toISOString(),
            },
          ],
        },
      );
      touchThread(threadId);
      void refreshSessions(projectId);
    } catch {
      // Error surfaced through stream state.
    } finally {
      submitLockRef.current = false;
    }
  }

  async function handleSubmitIntervention() {
    if (submitLockRef.current || stream.isLoading) {
      return;
    }

    const text = interventionDraft.trim();
    if (!text) {
      return;
    }

    submitLockRef.current = true;
    try {
      await stream.submit(null, {
        projectId,
        command: {
          update: {
            messages: [
              {
                type: "human",
                content: text,
              },
            ],
          },
          resume: { action: "continue_with_guidance" },
        },
        optimisticTurns: [
          {
            id: `local-guidance-${Date.now()}`,
            role: "user",
            content: text,
            created_at: new Date().toISOString(),
          },
        ],
      });
      setInterventionDraft("");
      touchThread(stream.threadId);
      void refreshSessions(projectId);
    } catch {
      // Error surfaced through stream state.
    } finally {
      submitLockRef.current = false;
    }
  }

  async function openThread(thread: ChatThreadSummary) {
    try {
      await stream.restoreSession({ projectId: thread.projectId, threadId: thread.id });
      touchThread(thread.id);
    } catch {
      stream.resetThread(thread.id);
    }
  }

  function createNewThread() {
    stream.resetThread();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }

    event.preventDefault();
    void handleSendMessage();
  }

  function upsertThreadSummary(summary: ChatThreadSummary) {
    setServerThreads((current) => {
      const nextThreads = current.filter((thread) => thread.id !== summary.id);
      nextThreads.unshift(summary);
      return nextThreads;
    });
  }

  function touchThread(threadId: string) {
    setServerThreads((current) =>
      current.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              updatedAt: new Date().toISOString(),
            }
          : thread,
      ),
    );
  }

  async function refreshSessions(currentProjectId: string) {
    const sessions = await stream.listSessions(currentProjectId);
    setServerThreads(sessions.map(toThreadSummary));
  }

  return (
    <section className={`chat-board ${showThreadSidebar ? "with-sidebar" : "single-pane"} ${compact ? "compact" : "regular"}`}>
      {showThreadSidebar ? (
        <aside className="chat-sidebar">
          <div className="chat-sidebar-header">
            <div>
              <p className="section-kicker">项目</p>
              <h3>{projectId}</h3>
            </div>
            <button className="button subtle small-button" onClick={createNewThread}>
              新对话
            </button>
          </div>

          <div className="chat-project-group-list">
            {Object.entries(groupedThreads).length === 0 ? (
              <div className="chat-sidebar-empty">当前还没有历史对话。</div>
            ) : (
              Object.entries(groupedThreads).map(([groupProjectId, threads]) => (
                <section className="chat-project-group" key={groupProjectId}>
                  <div className="chat-project-group-title">{groupProjectId}</div>
                  <div className="chat-thread-list">
                    {threads.map((thread) => (
                      <button
                        key={thread.id}
                        className={`chat-thread-item ${thread.id === stream.threadId ? "active" : ""}`}
                        onClick={() => void openThread(thread)}
                      >
                        <strong>{thread.title}</strong>
                        <span>{formatRelativeTime(thread.updatedAt)}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
        </aside>
      ) : null}

      <section className="chat-main">
        <header className="chat-main-header">
          <div>
            <h2>{title}</h2>
            {description ? <p className="chat-description">{description}</p> : null}
            {contextLabel ? <div className="chat-context-banner">{contextLabel}</div> : null}
          </div>
          <div className="chat-header-actions">
            <span className={`chip chat-status-chip ${stream.isLoading ? "loading" : "idle"}`}>
              {stream.isLoading ? "流式生成中" : "就绪"}
            </span>
            <button
              className="button subtle small-button"
              onClick={() => setShowSummaries((current) => !current)}
            >
              {showSummaries ? "隐藏摘要" : "显示摘要"}
            </button>
            {!showThreadSidebar ? (
              <button className="button subtle small-button" onClick={createNewThread}>
                新对话
              </button>
            ) : null}
          </div>
        </header>

        {stream.error ? (
          <p className="error-message">对话流失败：{stream.error.message}</p>
        ) : null}

        <div className="chat-scroll-area">
          {stream.turns.length === 0 ? (
            <div className="chat-empty-state">
              <h3>开始新的对话</h3>
              <p>你可以让 AI 解释论文、做分析、比较方法，或者帮你规划复现步骤。</p>
            </div>
          ) : (
            stream.turns.map((turn) => (
              <ChatTurnBubble
                key={turn.id}
                turn={turn}
                showSummary={showSummaries}
                onToggleTrace={() => stream.toggleTurnCollapsed(turn.id)}
              />
            ))
          )}
        </div>

        {stream.interrupt ? (
          <InterruptPanel
            interrupt={stream.interrupt}
            interventionDraft={interventionDraft}
            onInterventionDraftChange={setInterventionDraft}
            onContinue={() =>
              void stream.submit(null, {
                projectId,
                command: { resume: { action: "continue" } },
              })
            }
            onSubmitIntervention={() => void handleSubmitIntervention()}
          />
        ) : null}

        <div className="chat-composer">
          <textarea
            className="input textarea chat-composer-input"
            rows={compact ? 4 : 5}
            placeholder={placeholder}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
          />
          <div className="chat-composer-actions">
            <button className="button subtle small-button" onClick={() => stream.stop()} disabled={!stream.isLoading}>
              停止
            </button>
            <button
              className="button primary send-button"
              onClick={() => void handleSendMessage()}
              disabled={stream.isLoading || !draft.trim()}
            >
              发送
            </button>
          </div>
        </div>
      </section>
    </section>
  );
}

function InterruptPanel({
  interrupt,
  interventionDraft,
  onInterventionDraftChange,
  onContinue,
  onSubmitIntervention,
}: {
  interrupt: InterruptPayload<LoopInterruptValue>;
  interventionDraft: string;
  onInterventionDraftChange: (value: string) => void;
  onContinue: () => void;
  onSubmitIntervention: () => void;
}) {
  return (
    <section className="chat-interrupt-panel">
      <strong>当前流程已暂停</strong>
      {interrupt.value.question ? <p>{interrupt.value.question}</p> : null}
      <div className="button-row">
        <button className="button subtle small-button" onClick={onContinue}>
          继续
        </button>
      </div>
      <textarea
        className="input textarea"
        rows={3}
        placeholder="给当前流程补充指导"
        value={interventionDraft}
        onChange={(event) => onInterventionDraftChange(event.target.value)}
      />
      <button className="button primary small-button" onClick={onSubmitIntervention}>
        注入指导
      </button>
    </section>
  );
}

function ChatTurnBubble({
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
      <article className="chat-message user">
        <div className="chat-message-label">我</div>
        <div className="chat-message-body">{turn.content ?? ""}</div>
      </article>
    );
  }

  const traceItems = turn.trace_items ?? [];
  const citations = turn.citations ?? [];
  const assetCitations = turn.asset_citations ?? [];
  const assetSources = turn.asset_sources ?? [];
  const webSources = turn.web_sources ?? [];
  const toolSources = turn.tool_sources ?? [];
  const summary = turn.summary;
  const traceButtonLabel = turn.status === "streaming" ? "思考中" : turn.collapsed ? "已完成思考" : "收起思考";

  return (
    <article className="chat-message assistant">
      <div className="chat-message-label">AI</div>

      {traceItems.length > 0 ? (
        <div className="chat-trace-shell">
          <button className="chat-trace-toggle" onClick={onToggleTrace}>
            {traceButtonLabel}
          </button>
          {!turn.collapsed ? (
            <div className="chat-trace-panel">
              {traceItems.map((item) => (
                <TraceItemRow key={item.id} item={item} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="chat-message-body">
        {turn.answer_text ? <MarkdownRenderer content={turn.answer_text} assetSources={assetSources} /> : null}
      </div>

      {showSummary && summary ? (
        <div className="chat-message-summary">
          {summary.done ? <p>已完成：{summary.done}</p> : null}
          {summary.next ? <p>下一步：{summary.next}</p> : null}
          {summary.pending ? <p>未完成：{summary.pending}</p> : null}
        </div>
      ) : null}

      {citations.length > 0 ? (
        <div className="citation-row">
          {citations.map((citation) => (
            <span className="chip citation-chip" key={`${citation.chunk_id}-${citation.locator ?? citation.page ?? "source"}`}>
              {citation.document_title} {citation.locator ?? (citation.page ? `p.${citation.page}` : "")}
            </span>
          ))}
        </div>
      ) : null}

      {assetCitations.length > 0 ? (
        <div className="citation-row">
          {assetCitations.map((citation) => (
            <span className="chip citation-chip" key={`${citation.asset_id}-${citation.locator ?? citation.page ?? "asset"}`}>
              {citation.label || "图片证据"} {citation.locator ?? (citation.page ? `p.${citation.page}` : "")}
            </span>
          ))}
        </div>
      ) : null}

      {assetSources.length > 0 ? (
        <div className="asset-source-grid">
          {assetSources.map((source) => (
            <article className="asset-source-card" key={source.asset_id}>
              {source.file_url ? (
                <img
                  className="asset-source-image"
                  src={`${apiBase}${source.file_url}`}
                  alt={source.asset_label || source.file_name || "图片证据"}
                  loading="lazy"
                />
              ) : (
                <div className="asset-source-image empty-image">预览不可用</div>
              )}
              <div className="asset-source-copy">
                <strong>{source.asset_label || source.file_name || "图片证据"}</strong>
                <p>{source.summary || source.caption || "没有图片摘要"}</p>
                <small>{source.page_number ? `p.${source.page_number}` : source.asset_type || ""}</small>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {webSources.length > 0 ? (
        <div className="citation-row">
          {webSources.map((source) => (
            <a className="chip citation-chip" key={source.url} href={source.url} target="_blank" rel="noreferrer">
              {source.title || source.url}
            </a>
          ))}
        </div>
      ) : null}

      {toolSources.length > 0 ? (
        <div className="citation-row">
          {toolSources.map((source, index) =>
            source.url ? (
              <a
                className="chip citation-chip"
                key={`${source.url}-${index}`}
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                {source.title || source.tool_name || "工具来源"}
              </a>
            ) : (
              <span className="chip citation-chip" key={`${source.title}-${index}`}>
                {source.title || source.tool_name || "工具来源"}
              </span>
            ),
          )}
        </div>
      ) : null}
    </article>
  );
}

function TraceItemRow({ item }: { item: ChatTraceItem }) {
  return (
    <div className={`chat-trace-item ${item.kind}`}>
      <div className="chat-trace-item-head">
        <strong>{traceItemLabel(item)}</strong>
      </div>
      <div className="chat-trace-item-body">{item.text}</div>
    </div>
  );
}

function traceItemLabel(item: ChatTraceItem): string {
  if (item.kind === "tool_call") {
    return item.title || "工具调用";
  }
  if (item.kind === "tool_result") {
    return item.title || "工具结果";
  }
  return item.title || "思考";
}

function groupThreadsByProject(threads: ChatThreadSummary[]) {
  return threads.reduce<Record<string, ChatThreadSummary[]>>((groups, thread) => {
    if (!groups[thread.projectId]) {
      groups[thread.projectId] = [];
    }
    groups[thread.projectId].push(thread);
    groups[thread.projectId].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
    return groups;
  }, {});
}

function buildThreadTitle(content: string) {
  return content.length > 24 ? `${content.slice(0, 24)}...` : content;
}

function toThreadSummary(session: ChatSessionSummary): ChatThreadSummary {
  return {
    id: session.session_id,
    title: session.title,
    projectId: session.project_id,
    updatedAt: session.updated_at,
  };
}

function formatRelativeTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function buildDocumentFileUrl(path: string): string {
  return `${apiBase}/documents/file?path=${encodeURIComponent(path)}`;
}
