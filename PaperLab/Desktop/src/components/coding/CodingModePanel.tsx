import { useEffect, useRef, useState, useCallback } from "react";
import {
  Terminal,
  Play,
  CheckCircle,
  XCircle,
  ChevronRight,
  FileCode,
  Loader2,
  Square,
} from "lucide-react";

const apiBase = import.meta.env.VITE_CODING_API_URL ?? "http://127.0.0.1:8001";

/* ── 类型 ── */

interface AgentAction {
  action_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  approved: boolean | null;
  timestamp: number;
}

interface SessionState {
  session_id: string;
  phase: string;
  iteration: number;
  plan: string;
  paper_context: string;
  actions: AgentAction[];
  pending_action: AgentAction | null;
  error: string;
  summary: string;
}

interface ChatEntry {
  id: string;
  role: "assistant" | "system" | "user" | "tool";
  content: string;
  timestamp: number;
}

/* ── 工具名映射 ── */

const TOOL_LABELS: Record<string, string> = {
  read_file: "读取文件",
  write_file: "写入文件",
  edit_file: "编辑文件",
  list_files: "列出文件",
  search_text: "搜索文本",
  run_command: "执行命令",
  install_packages: "安装包",
  run_python: "执行 Python",
  finish: "完成",
};

const PHASE_LABELS: Record<string, string> = {
  init: "初始化",
  planning: "规划中",
  coding: "编写代码",
  executing: "执行中",
  fixing: "修复中",
  done: "完成",
  failed: "失败",
  waiting_approval: "等待审批",
};

/* ── 主组件 ── */

export function CodingModePanel({
  paperContext,
  onExit,
}: {
  paperContext: string;
  onExit: () => void;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState<SessionState | null>(null);
  const [chat, setChat] = useState<ChatEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRun, setAutoRun] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动
  useEffect(() => {
    if (scrollRef.current) {
      requestAnimationFrame(() => {
        scrollRef.current!.scrollTop = scrollRef.current!.scrollHeight;
      });
    }
  }, [chat, state]);

  // 创建会话
  const initSession = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${apiBase}/coding/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paper_context: paperContext,
          objective: "Reproduce the paper experiments",
        }),
      });
      const data = await resp.json();
      setSessionId(data.session_id);
      addChat("system", `会话已创建: ${data.session_id}`);
    } catch (err) {
      addChat("system", `创建会话失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [paperContext]);

  // 获取状态
  const fetchState = useCallback(async (sid: string) => {
    try {
      const resp = await fetch(`${apiBase}/coding/sessions/${sid}`);
      const data: SessionState = await resp.json();
      setState(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  // 执行一步
  const runStep = useCallback(async () => {
    if (!sessionId || loading) return;
    setLoading(true);
    try {
      const resp = await fetch(`${apiBase}/coding/sessions/${sessionId}/step`, {
        method: "POST",
      });
      const data: SessionState = await resp.json();
      setState(data);

      // 处理新动作
      const lastAction = data.actions[data.actions.length - 1];
      if (lastAction && lastAction.result) {
        const label = TOOL_LABELS[lastAction.tool_name] || lastAction.tool_name;
        if (lastAction.tool_name === "finish") {
          addChat("assistant", `✅ 任务完成: ${data.summary}`);
        } else {
          addChat("tool", `[${label}] ${formatResult(lastAction.result)}`);
        }
      }

      // 需要审批
      if (data.pending_action) {
        const pa = data.pending_action;
        addChat("system", `⚠️ 需要审批: ${TOOL_LABELS[pa.tool_name] || pa.tool_name}`);
      }
    } catch (err) {
      addChat("system", `执行失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [sessionId, loading]);

  // 审批
  const approve = useCallback(
    async (approved: boolean) => {
      if (!sessionId) return;
      setLoading(true);
      try {
        const resp = await fetch(`${apiBase}/coding/sessions/${sessionId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, approved }),
        });
        const data: SessionState = await resp.json();
        setState(data);
        addChat("system", approved ? "✅ 已批准" : "❌ 已拒绝");
      } finally {
        setLoading(false);
      }
    },
    [sessionId],
  );

  // 自动循环
  useEffect(() => {
    if (!autoRun || !sessionId || loading) return;
    if (state?.phase === "waiting_approval" || state?.phase === "done" || state?.phase === "failed") {
      setAutoRun(false);
      return;
    }
    const timer = setTimeout(() => void runStep(), 500);
    return () => clearTimeout(timer);
  }, [autoRun, sessionId, loading, state?.phase, runStep]);

  function addChat(role: ChatEntry["role"], content: string) {
    setChat((prev) => [
      ...prev,
      { id: `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`, role, content, timestamp: Date.now() },
    ]);
  }

  // 初始化
  useEffect(() => {
    void initSession();
  }, [initSession]);

  const pendingAction = state?.pending_action;

  return (
    <div className="coding-mode">
      {/* ── 顶栏 ── */}
      <header className="coding-header">
        <div className="coding-header-left">
          <Terminal size={18} className="coding-icon" />
          <span className="coding-title">Coding Reproduction Mode</span>
          {state ? (
            <span className="coding-phase">{PHASE_LABELS[state.phase] || state.phase}</span>
          ) : null}
        </div>
        <div className="coding-header-right">
          {state?.phase === "done" ? (
            <span className="coding-badge coding-badge-success">完成</span>
          ) : state?.phase === "failed" ? (
            <span className="coding-badge coding-badge-error">失败</span>
          ) : null}
          <button className="coding-btn coding-btn-ghost" onClick={onExit}>
            退出
          </button>
        </div>
      </header>

      <div className="coding-body">
        {/* ── 左侧：文件树 + 状态 ── */}
        <aside className="coding-sidebar">
          <div className="coding-sidebar-section">
            <h4 className="coding-sidebar-title">会话状态</h4>
            {state ? (
              <div className="coding-status-grid">
                <div className="coding-status-item">
                  <span className="coding-status-label">迭代</span>
                  <span className="coding-status-value">{state.iteration}</span>
                </div>
                <div className="coding-status-item">
                  <span className="coding-status-label">阶段</span>
                  <span className="coding-status-value">{PHASE_LABELS[state.phase] || state.phase}</span>
                </div>
                <div className="coding-status-item">
                  <span className="coding-status-label">动作数</span>
                  <span className="coding-status-value">{state.actions.length}</span>
                </div>
              </div>
            ) : (
              <span className="coding-text-muted">初始化中...</span>
            )}
          </div>

          <div className="coding-sidebar-section">
            <h4 className="coding-sidebar-title">执行历史</h4>
            <div className="coding-action-list">
              {state?.actions.map((action, i) => (
                <div key={action.action_id} className={`coding-action-item ${action.approved ? "" : "rejected"}`}>
                  <div className="coding-action-header">
                    <span className="coding-action-index">#{i + 1}</span>
                    <span className="coding-action-name">{TOOL_LABELS[action.tool_name] || action.tool_name}</span>
                    {action.approved === false ? <XCircle size={12} className="coding-icon-error" /> : <CheckCircle size={12} className="coding-icon-success" />}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {state?.plan ? (
            <div className="coding-sidebar-section">
              <h4 className="coding-sidebar-title">复现计划</h4>
              <pre className="coding-plan">{state.plan}</pre>
            </div>
          ) : null}
        </aside>

        {/* ── 中间：对话流 ── */}
        <main className="coding-main">
          <div className="coding-chat-scroll" ref={scrollRef}>
            {chat.length === 0 && !state ? (
              <div className="coding-empty">
                <FileCode size={48} className="coding-empty-icon" />
                <h3>正在初始化 Coding Agent...</h3>
                <p>正在创建沙箱环境和加载工具集</p>
              </div>
            ) : (
              chat.map((entry) => (
                <div key={entry.id} className={`coding-msg coding-msg-${entry.role}`}>
                  <div className="coding-msg-role">
                    {entry.role === "assistant" ? "🤖 Agent" : entry.role === "tool" ? "🔧 工具" : entry.role === "user" ? "👤 你" : "⚙️ 系统"}
                  </div>
                  <div className="coding-msg-content">
                    <pre>{entry.content}</pre>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* ── 审批面板 ── */}
          {pendingAction ? (
            <div className="coding-approval-panel">
              <div className="coding-approval-header">
                <span className="coding-approval-title">⚠️ 需要审批</span>
                <span className="coding-approval-tool">{TOOL_LABELS[pendingAction.tool_name] || pendingAction.tool_name}</span>
              </div>
              <pre className="coding-approval-args">{JSON.stringify(pendingAction.args, null, 2)}</pre>
              <div className="coding-approval-actions">
                <button className="coding-btn coding-btn-primary" onClick={() => void approve(true)} disabled={loading}>
                  <CheckCircle size={14} /> 批准执行
                </button>
                <button className="coding-btn coding-btn-danger" onClick={() => void approve(false)} disabled={loading}>
                  <XCircle size={14} /> 拒绝
                </button>
              </div>
            </div>
          ) : null}

          {/* ── 底部控制栏 ── */}
          <div className="coding-controls">
            <button
              className="coding-btn coding-btn-primary"
              onClick={() => void runStep()}
              disabled={loading || !sessionId || state?.phase === "done" || state?.phase === "failed" || state?.phase === "waiting_approval"}
            >
              {loading ? <Loader2 size={14} className="coding-spin" /> : <Play size={14} />}
              执行一步
            </button>
            <button
              className={`coding-btn ${autoRun ? "coding-btn-danger" : "coding-btn-primary"}`}
              onClick={() => setAutoRun((c) => !c)}
              disabled={!sessionId || state?.phase === "done" || state?.phase === "failed"}
            >
              {autoRun ? <Square size={14} /> : <ChevronRight size={14} />}
              {autoRun ? "停止自动" : "自动运行"}
            </button>
            {state?.summary ? (
              <div className="coding-summary">
                <span>📋 {state.summary}</span>
              </div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}

/* ── 工具函数 ── */

function formatResult(result: Record<string, unknown>): string {
  if (result.error) return `❌ ${result.error}`;
  if (result.success === false) return `❌ ${result.stderr || result.output || "failed"}`;
  if (result.stdout) return result.stdout.slice(0, 300);
  if (result.output) return result.output.slice(0, 300);
  if (result.content) return result.content.slice(0, 300);
  return JSON.stringify(result).slice(0, 300);
}
