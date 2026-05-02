import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { MessageSquare, AlertCircle } from "lucide-react";
import type { ChatSessionSummary } from "../../types";
import { usePaperLabStream } from "../../usePaperLabStream";
import { ChatMessage } from "./ChatMessage";
import { ChatComposer } from "./ChatComposer";
import { ThreadSidebar } from "./ThreadSidebar";

type LoopInterruptValue = { phase?: string; question?: string };

type ChatThreadSummary = {
  id: string;
  title: string;
  projectId: string;
  updatedAt: string;
};

const apiBase = import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";

export function ChatPanel({
  projectId,
  title,
  description,
  placeholder,
  contextLabel,
  compact = false,
  showThreadSidebar = false,
  collapseButton,
}: {
  projectId: string;
  title: string;
  description?: string;
  placeholder: string;
  contextLabel?: string;
  compact?: boolean;
  showThreadSidebar?: boolean;
  collapseButton?: React.ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const [interventionDraft, setInterventionDraft] = useState("");
  const [showSummaries, setShowSummaries] = useState(false);
  const [serverThreads, setServerThreads] = useState<ChatThreadSummary[]>([]);
  const submitLockRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const stream = usePaperLabStream<LoopInterruptValue>({ apiBaseUrl: apiBase });

  const groupedThreads = useMemo(() => {
    const groups: Record<string, ChatThreadSummary[]> = {};
    for (const t of serverThreads) {
      if (!groups[t.projectId]) groups[t.projectId] = [];
      groups[t.projectId].push(t);
    }
    for (const key of Object.keys(groups)) {
      groups[key].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    }
    return groups;
  }, [serverThreads]);

  const flatThreads = useMemo(() => {
    return Object.values(groupedThreads).flat();
  }, [groupedThreads]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [stream.turns]);

  // Load sessions on mount
  useEffect(() => {
    let cancelled = false;
    void stream
      .listSessions(projectId)
      .then((sessions) => {
        if (cancelled) return;
        const threads = sessions.map(toThreadSummary);
        setServerThreads(threads);
        const latest = threads[0];
        if (!latest) { stream.resetThread(); return; }
        void stream.restoreSession({ projectId, threadId: latest.id }).catch(() => {
          if (!cancelled) stream.resetThread(latest.id);
        });
      })
      .catch(() => {
        if (!cancelled) { setServerThreads([]); stream.resetThread(); }
      });
    return () => { cancelled = true; };
  }, [projectId]);

  async function handleSend() {
    if (submitLockRef.current || stream.isLoading) return;
    const text = draft.trim();
    if (!text) return;

    upsertThread({ id: stream.threadId, title: text.slice(0, 24), projectId, updatedAt: new Date().toISOString() });
    setDraft("");
    submitLockRef.current = true;

    try {
      await stream.submit(
        { messages: [{ type: "human", content: text }] },
        {
          projectId,
          optimisticTurns: [{ id: `local-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() }],
        },
      );
      touchThread(stream.threadId);
      void refreshSessions();
    } catch { /* error in stream state */ } finally {
      submitLockRef.current = false;
    }
  }

  async function handleIntervention() {
    if (submitLockRef.current || stream.isLoading) return;
    const text = interventionDraft.trim();
    if (!text) return;

    submitLockRef.current = true;
    try {
      await stream.submit(null, {
        projectId,
        command: {
          update: { messages: [{ type: "human", content: text }] },
          resume: { action: "continue_with_guidance" },
        },
        optimisticTurns: [{ id: `local-guidance-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() }],
      });
      setInterventionDraft("");
      touchThread(stream.threadId);
      void refreshSessions();
    } catch { /* error in stream state */ } finally {
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

  function upsertThread(summary: ChatThreadSummary) {
    setServerThreads((current) => {
      const next = current.filter((t) => t.id !== summary.id);
      next.unshift(summary);
      return next;
    });
  }

  function touchThread(threadId: string) {
    setServerThreads((current) =>
      current.map((t) => (t.id === threadId ? { ...t, updatedAt: new Date().toISOString() } : t)),
    );
  }

  async function refreshSessions() {
    const sessions = await stream.listSessions(projectId);
    setServerThreads(sessions.map(toThreadSummary));
  }

  return (
    <section className={`chat-board ${showThreadSidebar ? "with-sidebar" : ""}`}>
      {showThreadSidebar ? (
        <ThreadSidebar
          threads={flatThreads}
          activeThreadId={stream.threadId}
          onSelect={openThread}
          onNew={() => stream.resetThread()}
        />
      ) : null}

      <div className="chat-layout">
        <div className="chat-header">
          <div className="chat-header-info">
            <span className="chat-header-title">{title}</span>
            {description ? <span className="chat-header-desc">{description}</span> : null}
            {contextLabel ? <span className="chat-context-tag">{contextLabel}</span> : null}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {collapseButton}
            <button className="btn btn-ghost btn-sm" onClick={() => setShowSummaries((c) => !c)}>
              {showSummaries ? "隐藏摘要" : "摘要"}
            </button>
            {!showThreadSidebar ? (
              <button className="btn btn-ghost btn-sm" onClick={() => stream.resetThread()}>
                新对话
              </button>
            ) : null}
          </div>
        </div>

        {stream.error ? (
          <div className="error-banner">
            <AlertCircle size={14} />
            对话流失败：{stream.error.message}
          </div>
        ) : null}

        <div className="chat-scroll-area" ref={scrollRef}>
          {stream.turns.length === 0 ? (
            <div className="chat-empty">
              <MessageSquare className="chat-empty-icon" />
              <h3>开始新的对话</h3>
              <p>你可以让 AI 解释论文、做分析、比较方法，或者帮你规划复现步骤。</p>
            </div>
          ) : (
            stream.turns.map((turn) => (
              <ChatMessage
                key={turn.id}
                turn={turn}
                showSummary={showSummaries}
                onToggleTrace={() => stream.toggleTurnCollapsed(turn.id)}
              />
            ))
          )}
        </div>

        {stream.interrupt ? (
          <div className="interrupt-panel">
            <strong>当前流程已暂停</strong>
            {stream.interrupt.value.question ? <p>{stream.interrupt.value.question}</p> : null}
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-sm" onClick={() => stream.submit(null, { projectId, command: { resume: { action: "continue" } } })}>
                继续
              </button>
            </div>
            <textarea
              className="input textarea"
              rows={2}
              placeholder="给当前流程补充指导"
              value={interventionDraft}
              onChange={(e) => setInterventionDraft(e.target.value)}
            />
            <button className="btn btn-primary btn-sm" onClick={() => void handleIntervention()}>
              注入指导
            </button>
          </div>
        ) : null}

        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={() => void handleSend()}
          onStop={() => stream.stop()}
          isLoading={stream.isLoading}
          placeholder={placeholder}
        />
      </div>
    </section>
  );
}

function toThreadSummary(session: ChatSessionSummary): ChatThreadSummary {
  return {
    id: session.session_id,
    title: session.title,
    projectId: session.project_id,
    updatedAt: session.updated_at,
  };
}
