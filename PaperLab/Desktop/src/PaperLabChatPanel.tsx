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
import {
  Wrench,
  Plug,
  Globe,
  FileText,
  FileEdit,
  Terminal,
  Cpu,
  FolderRoot,
  ShieldAlert,
} from "lucide-react";

type LoopInterruptValue = {
  type?: string;
  phase?: string;
  question?: string;
  approval?: {
    tool_call_id: string;
    tool_name: string;
    args: Record<string, unknown>;
    risk: string;
    platform: Record<string, unknown>;
    preview: string;
  };
};

type ChatThreadSummary = {
  id: string;
  title: string;
  projectId: string;
  updatedAt: string;
};

type PaperLabChatPanelProps = {
  projectId: string;
  rootPath?: string;
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
  rootPath = "",
  title,
  description = "",
  placeholder,
  contextLabel = "",
  compact = false,
  showThreadSidebar = false,
}: PaperLabChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [showSummaries, setShowSummaries] = useState(false);
  const [toolSettings, setToolSettings] = useState<{
    allow_web_search: boolean;
    allow_file_read: boolean;
    allow_file_write: boolean;
    allow_mcp: boolean;
    allow_shell: boolean;
    workspace_root: string;
  }>(() => {
    const saved = localStorage.getItem("paperlab_tool_settings");
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        // ignore
      }
    }
    return {
      allow_web_search: false,
      allow_file_read: false,
      allow_file_write: false,
      allow_mcp: false,
      allow_shell: false,
      workspace_root: localStorage.getItem("paperlab_workspace_root") || "",
    };
  });
  const [serverThreads, setServerThreads] = useState<ChatThreadSummary[]>([]);
  const submitLockRef = useRef(false);
  const guidanceQueueLockRef = useRef(false);
  const stream = usePaperLabStream<LoopInterruptValue>({
    apiBaseUrl: apiBase,
  });

  const groupedThreads = useMemo(() => groupThreadsByProject(serverThreads), [serverThreads]);

  useEffect(() => {
    localStorage.setItem("paperlab_tool_settings", JSON.stringify(toolSettings));
  }, [toolSettings]);

  const toolDefinitions = useMemo(
    () => [
      { key: "allow_web_search" as const, name: "网络搜索", desc: "搜索外部信息", icon: Globe },
      { key: "allow_file_read" as const, name: "文件读取", desc: "读取工作区文件", icon: FileText },
      { key: "allow_file_write" as const, name: "文件写入", desc: "创建和修改文件", icon: FileEdit },
      { key: "allow_mcp" as const, name: "MCP 工具", desc: "连接外部 CodingAgent", icon: Plug },
      { key: "allow_shell" as const, name: "Shell 执行", desc: "执行系统命令", icon: Terminal },
    ],
    [],
  );

  const [mcpServers, setMcpServers] = useState<{ id: string; transport: string; connected: boolean }[]>([]);

  useEffect(() => {
    if (!toolSettings.allow_mcp) {
      setMcpServers([]);
      return;
    }
    let cancelled = false;
    fetch(`${apiBase}/mcp/servers`)
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data: { enabled: boolean; servers: { server_id: string; transport: string; command: string }[] }) => {
        if (cancelled) return;
        setMcpServers(
          data.servers.map((s) => ({
            id: s.server_id,
            transport: s.transport,
            connected: false,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setMcpServers([]);
      });
    return () => { cancelled = true; };
  }, [toolSettings.allow_mcp]);

  // Set default workspace root to {rootPath's parent}/workspace
  useEffect(() => {
    if (!rootPath || toolSettings.workspace_root) return;
    const parent = rootPath.replace(/[\\/][^\\/]+$/, "");
    const defaultWs = parent ? `${parent}/workspace` : "";
    if (defaultWs) {
      setToolSettings((current) => ({ ...current, workspace_root: defaultWs }));
    }
  }, [rootPath]);

  const [choosingWorkspace, setChoosingWorkspace] = useState(false);

  async function chooseWorkspaceFolder() {
    setChoosingWorkspace(true);
    try {
      const response = await fetch(`${apiBase}/desktop/project-folder/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_path: toolSettings.workspace_root || undefined }),
      });
      if (!response.ok) return;
      const payload = (await response.json()) as { path: string };
      if (payload.path) {
        setToolSettings((current) => ({ ...current, workspace_root: payload.path }));
      }
    } catch {
      // silently ignore
    } finally {
      setChoosingWorkspace(false);
    }
  }

  const enabledToolCount = useMemo(
    () =>
      [
        toolSettings.allow_web_search,
        toolSettings.allow_file_read,
        toolSettings.allow_file_write,
        toolSettings.allow_mcp,
        toolSettings.allow_shell,
      ].filter(Boolean).length,
    [toolSettings],
  );

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
    const text = draft.trim();
    if (!text) {
      return;
    }

    const threadId = stream.threadId;
    if (stream.isLoading) {
      if (guidanceQueueLockRef.current) {
        return;
      }
      guidanceQueueLockRef.current = true;
      setDraft("");
      try {
        await stream.queueGuidance({
          projectId,
          threadId,
          content: text,
          optimisticTurn: {
            id: `local-guidance-${Date.now()}`,
            role: "user",
            content: text,
            created_at: new Date().toISOString(),
          },
        });
      } catch {
        setDraft(text);
      } finally {
        guidanceQueueLockRef.current = false;
      }
      return;
    }

    if (submitLockRef.current) {
      return;
    }

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
          toolsEnabled: Object.values(toolSettings).some((value) => Boolean(value)),
          toolSettings,
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

  async function openThread(thread: ChatThreadSummary) {
    if (thread.id === stream.threadId) return;
    try {
      await stream.restoreSession({ projectId: thread.projectId, threadId: thread.id });
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
    <section className={`paperlab-solo-panel chat-board ${showThreadSidebar ? "with-sidebar" : "single-pane"} ${compact ? "compact" : "regular"}`}>
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
            <p className="section-kicker">AI SOLO</p>
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

        {stream.interrupt?.value.type === "tool_approval" ? (
          <ToolApprovalPanel
            interrupt={stream.interrupt}
            onApprove={() =>
              void stream.submit(null, {
                projectId,
                toolsEnabled: Object.values(toolSettings).some((value) => Boolean(value)),
                toolSettings,
                command: { resume: { action: "approve" } },
              })
            }
            onReject={() =>
              void stream.submit(null, {
                projectId,
                toolsEnabled: Object.values(toolSettings).some((value) => Boolean(value)),
                toolSettings,
                command: { resume: { action: "reject" } },
              })
            }
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
              disabled={!draft.trim()}
            >
              发送
            </button>
          </div>
        </div>
      </section>

      {/* Right panel: tool controls */}
      <SoloToolPanel
        toolDefinitions={toolDefinitions}
        toolSettings={toolSettings}
        onToggleTool={(key) =>
          setToolSettings((current) => ({ ...current, [key]: !current[key] }))
        }
        onWorkspaceRootChange={(value) =>
          setToolSettings((current) => ({ ...current, workspace_root: value }))
        }
        onChooseWorkspaceFolder={() => void chooseWorkspaceFolder()}
        choosingWorkspace={choosingWorkspace}
        mcpServers={mcpServers}
        enabledToolCount={enabledToolCount}
      />
    </section>
  );
}

function ToolApprovalPanel({
  interrupt,
  onApprove,
  onReject,
}: {
  interrupt: InterruptPayload<LoopInterruptValue>;
  onApprove: () => void;
  onReject: () => void;
}) {
  const approval = interrupt.value.approval;
  if (!approval) return null;
  return (
    <section className="chat-interrupt-panel">
      <strong>工具调用审批</strong>
      <p>{approval.preview || interrupt.value.question}</p>
      <div className="chat-tool-approval-meta">
        <span>工具：{approval.tool_name}</span>
        <span>风险：{approval.risk}</span>
        <span>系统：{String(approval.platform?.system ?? "")}</span>
      </div>
      <pre className="chat-tool-approval-args">
        {JSON.stringify(approval.args, null, 2)}
      </pre>
      <div className="button-row">
        <button className="button primary small-button" onClick={onApprove}>
          批准执行
        </button>
        <button className="button subtle small-button" onClick={onReject}>
          拒绝
        </button>
      </div>
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
          {toolSources.map((source, index) => {
            const isMcp = source.kind === "mcp";
            const chipClass = `chip citation-chip ${isMcp ? "citation-chip-mcp" : ""}`;
            const label = source.title || source.tool_name || "工具来源";
            const inner = isMcp ? <><Plug size={10} /> {label}</> : label;
            return source.url ? (
              <a
                className={chipClass}
                key={`${source.url}-${index}`}
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                {inner}
              </a>
            ) : (
              <span className={chipClass} key={`${source.title ?? label}-${index}`}>
                {inner}
              </span>
            );
          },
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

function SoloToolPanel({
  toolDefinitions,
  toolSettings,
  onToggleTool,
  onWorkspaceRootChange,
  onChooseWorkspaceFolder,
  choosingWorkspace,
  mcpServers,
  enabledToolCount,
}: {
  toolDefinitions: { key: keyof typeof toolSettings; name: string; desc: string; icon: typeof Globe }[];
  toolSettings: {
    allow_web_search: boolean;
    allow_file_read: boolean;
    allow_file_write: boolean;
    allow_mcp: boolean;
    allow_shell: boolean;
    workspace_root: string;
  };
  onToggleTool: (key: keyof typeof toolSettings) => void;
  onWorkspaceRootChange: (value: string) => void;
  onChooseWorkspaceFolder: () => void;
  choosingWorkspace: boolean;
  mcpServers: { id: string; transport: string; connected: boolean }[];
  enabledToolCount: number;
}) {
  return (
    <aside className="chat-right-panel">
      <div className="chat-right-panel-header">
        <span className="chat-right-panel-title">
          <Wrench size={14} />
          工具控制
        </span>
        <span className="chip">{enabledToolCount} 已启用</span>
      </div>

      <section className="tool-panel-section">
        <div className="tool-panel-section-head">
          <FolderRoot size={13} />
          工作目录
        </div>
        <p className="tool-panel-section-copy">所有文件工具与命令都以此目录为边界</p>
        <div className="workspace-root-row">
          <input
            className="input"
            aria-label="工作目录"
            placeholder="例如 C:/workspace/paperlab"
            value={toolSettings.workspace_root}
            onChange={(event) => onWorkspaceRootChange(event.target.value)}
          />
          <button
            type="button"
            className="btn btn-sm"
            onClick={onChooseWorkspaceFolder}
            disabled={choosingWorkspace}
            title="选择文件夹"
          >
            <FolderRoot size={14} />
            {choosingWorkspace ? "..." : "浏览"}
          </button>
        </div>
      </section>

      <section className="tool-panel-section">
        <div className="tool-panel-section-head">
          <ShieldAlert size={13} />
          权限开关
        </div>
        <p className="tool-panel-section-copy">
          Web 与 MCP 通过 Tool Agent 参与规划。Shell 属于高风险能力，启用后仍需逐次确认。
        </p>
        <div className="tool-cards">
        {toolDefinitions.map(({ key, name, desc, icon: Icon }) => (
          <div key={key} className={`tool-card ${toolSettings[key] ? "active" : ""}`}>
            <div className="tool-card-icon">
              <Icon size={14} />
            </div>
            <div className="tool-card-info">
              <div className="tool-card-name">{name}</div>
              <div className="tool-card-desc">{desc}</div>
            </div>
            <button
              type="button"
              className={`tool-card-toggle ${toolSettings[key] ? "on" : ""}`}
              onClick={() => onToggleTool(key)}
              aria-label={`切换${name}`}
            >
              <div className="toggle-thumb" />
            </button>
          </div>
        ))}
        </div>
      </section>

      <section className="tool-panel-section">
        <div className="mcp-section-title">
          <Cpu size={13} />
          MCP 服务器
        </div>

        {mcpServers.length === 0 ? (
          <div className="solo-empty-hint">
            启用 MCP 工具后
            <br />
            在这里显示连接状态与可用代理
          </div>
        ) : (
          <div className="mcp-server-list">
            {mcpServers.map((server) => (
              <div className="server-card" key={server.id}>
                <div className={`server-card-status ${server.connected ? "connected" : ""}`} />
                <div className="server-card-info">
                  <div className="server-card-name">{server.id}</div>
                  <div className="server-card-transport">{server.transport}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
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
