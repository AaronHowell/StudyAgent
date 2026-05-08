import { useCallback, useMemo, useRef, useState } from "react";
import type { ChatSessionSummary } from "./types";

export type ChatTraceItem = {
  id: string;
  kind: string;
  title: string;
  text: string;
  status: string;
  created_at?: string;
};

export type MessageSummary = {
  done: string;
  next: string;
  pending: string;
};

export type CitationRecord = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  page?: number | null;
  locator?: string;
};

export type AssetCitationRecord = {
  asset_id: string;
  document_id: string;
  document_title: string;
  page?: number | null;
  label?: string;
  locator?: string;
};

export type AssetSourceRecord = {
  ref_id?: string;
  asset_id: string;
  document_id: string;
  page_number?: number | null;
  asset_label?: string;
  caption?: string;
  summary?: string;
  asset_type?: string;
  file_name?: string;
  file_url?: string;
};

export type SourceRecord = {
  title?: string;
  url?: string;
  tool_name?: string;
};

export type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  created_at?: string;
  content?: string;
  answer_text?: string;
  status?: string;
  collapsed?: boolean;
  summary?: MessageSummary;
  citations?: CitationRecord[];
  asset_citations?: AssetCitationRecord[];
  asset_sources?: AssetSourceRecord[];
  web_sources?: SourceRecord[];
  tool_sources?: SourceRecord[];
  trace_items?: ChatTraceItem[];
};

export type InterruptPayload<TInterrupt extends Record<string, unknown>> = {
  id: string;
  value: TInterrupt;
};

type SnapshotPayload<TInterrupt extends Record<string, unknown>> = {
  session_id: string;
  thread_id: string;
  project_id: string;
  turns: ChatTurn[];
  interrupt: InterruptPayload<TInterrupt> | null;
  next_nodes?: string[];
  checkpoint?: Record<string, unknown> | null;
};

type SubmitOptions = {
  projectId: string;
  threadId?: string;
  toolsEnabled?: boolean;
  command?: {
    update?: {
      messages?: Array<{ type: string; content: string }>;
    };
    resume?: Record<string, unknown>;
  };
  optimisticTurns?: ChatTurn[];
};

type StreamSubmitInput = {
  messages: Array<{ type: string; content: string }>;
} | null;

type LoadStateOptions = {
  projectId: string;
  threadId: string;
};

type UsePaperLabStreamOptions<TInterrupt extends Record<string, unknown>> = {
  apiBaseUrl: string;
};

type UsePaperLabStreamResult<TInterrupt extends Record<string, unknown>> = {
  threadId: string;
  turns: ChatTurn[];
  interrupt: InterruptPayload<TInterrupt> | null;
  isLoading: boolean;
  error: Error | null;
  submit: (input: StreamSubmitInput, options: SubmitOptions) => Promise<void>;
  queueGuidance: (options: { projectId: string; threadId?: string; content: string; optimisticTurn?: ChatTurn }) => Promise<void>;
  restoreSession: (options: LoadStateOptions) => Promise<void>;
  listSessions: (projectId: string) => Promise<ChatSessionSummary[]>;
  deleteSession: (options: { projectId: string; sessionId: string }) => Promise<void>;
  stop: () => void;
  resetThread: (threadId?: string | null) => void;
  toggleTurnCollapsed: (turnId: string) => void;
};

type AssistantTurnStartedEvent = {
  turn_id: string;
  created_at?: string;
};

type TraceItemStartedEvent = {
  turn_id: string;
  item: ChatTraceItem;
};

type TraceItemDeltaEvent = {
  turn_id: string;
  item_id: string;
  delta: string;
};

type TraceItemCompletedEvent = {
  turn_id: string;
  item_id: string;
};

type AnswerDeltaEvent = {
  turn_id: string;
  delta: string;
};

type TurnCompletedEvent = {
  turn_id: string;
  summary?: MessageSummary;
  citations?: CitationRecord[];
  asset_citations?: AssetCitationRecord[];
  asset_sources?: AssetSourceRecord[];
  web_sources?: SourceRecord[];
  tool_sources?: SourceRecord[];
  turn?: Partial<ChatTurn>;
};

function createThreadId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `thread_${Math.random().toString(16).slice(2)}`;
}

function readSseFrame(frame: string): { event: string; data: string } {
  const lines = frame.split("\n");
  const event = lines
    .find((line) => line.startsWith("event:"))
    ?.replace("event:", "")
    .trim();
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace("data:", "").trim())
    .join("\n");
  return {
    event: event || "message",
    data,
  };
}

function ensureAssistantTurn(turns: ChatTurn[], event: AssistantTurnStartedEvent): ChatTurn[] {
  if (turns.some((turn) => turn.id === event.turn_id)) {
    return turns.map((turn) =>
      turn.id === event.turn_id
        ? {
            ...turn,
            role: "assistant",
            created_at: turn.created_at || event.created_at,
          }
        : turn,
    );
  }
  return [
    ...turns,
    {
      id: event.turn_id,
      role: "assistant",
      created_at: event.created_at,
      answer_text: "",
      status: "streaming",
      collapsed: true,
      trace_items: [],
      citations: [],
      asset_citations: [],
      asset_sources: [],
      web_sources: [],
      tool_sources: [],
      summary: { done: "", next: "", pending: "" },
    },
  ];
}

function upsertTraceItem(items: ChatTraceItem[], next: ChatTraceItem): ChatTraceItem[] {
  const existingIndex = items.findIndex((item) => item.id === next.id);
  if (existingIndex === -1) return [...items, next];
  return items.map((item, index) => (index === existingIndex ? { ...item, ...next } : item));
}

function appendTraceDelta(current: string, delta: string): string {
  if (!delta) return current;
  if (!current) return delta;
  if (current === delta || current.endsWith(delta)) return current;
  return `${current}${delta}`;
}

export function usePaperLabStream<TInterrupt extends Record<string, unknown>>({
  apiBaseUrl,
}: UsePaperLabStreamOptions<TInterrupt>): UsePaperLabStreamResult<TInterrupt> {
  const [threadId, setThreadId] = useState(createThreadId);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [interrupt, setInterrupt] = useState<InterruptPayload<TInterrupt> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const submitInFlightRef = useRef(false);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    submitInFlightRef.current = false;
    setIsLoading(false);
  }, []);

  const resetThread = useCallback((nextThreadId?: string | null) => {
    stop();
    setError(null);
    setInterrupt(null);
    setTurns([]);
    setThreadId(nextThreadId || createThreadId());
  }, [stop]);

  const restoreSession = useCallback(
    async ({ projectId, threadId: nextThreadId }: LoadStateOptions) => {
      stop();
      setError(null);

      const response = await fetch(
        `${apiBaseUrl}/sessions/${encodeURIComponent(nextThreadId)}/snapshot?project_id=${encodeURIComponent(projectId)}`,
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as SnapshotPayload<TInterrupt>;
      setThreadId(nextThreadId);
      setTurns(payload.turns ?? []);
      setInterrupt(payload.interrupt ?? null);
    },
    [apiBaseUrl, stop],
  );

  const listSessions = useCallback(
    async (projectId: string) => {
      const response = await fetch(
        `${apiBaseUrl}/sessions?project_id=${encodeURIComponent(projectId)}`,
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      return (await response.json()) as ChatSessionSummary[];
    },
    [apiBaseUrl],
  );

  const deleteSession = useCallback(
    async ({ projectId, sessionId }: { projectId: string; sessionId: string }) => {
      const response = await fetch(
        `${apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}?project_id=${encodeURIComponent(projectId)}`,
        { method: "DELETE" },
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }
    },
    [apiBaseUrl],
  );

  const toggleTurnCollapsed = useCallback((turnId: string) => {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === turnId
          ? {
              ...turn,
              collapsed: !turn.collapsed,
            }
          : turn,
      ),
    );
  }, []);

  const submit = useCallback(
    async (input: StreamSubmitInput, options: SubmitOptions) => {
      if (submitInFlightRef.current) {
        return;
      }

      stop();
      submitInFlightRef.current = true;
      setError(null);
      setIsLoading(true);
      setInterrupt(null);

      const controller = new AbortController();
      abortRef.current = controller;
      const currentThreadId = options.threadId || threadId;
      setThreadId(currentThreadId);

      if (options.optimisticTurns?.length) {
        setTurns((current) => [...current, ...options.optimisticTurns!]);
      }

      try {
        const response = await fetch(`${apiBaseUrl}/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            thread_id: currentThreadId,
            project_id: options.projectId,
            input,
            command: options.command,
            tools_enabled: Boolean(options.toolsEnabled),
          }),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(await response.text());
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });

          while (buffer.includes("\n\n")) {
            const boundary = buffer.indexOf("\n\n");
            const rawFrame = buffer.slice(0, boundary).trim();
            buffer = buffer.slice(boundary + 2);
            if (!rawFrame) {
              continue;
            }

            const frame = readSseFrame(rawFrame);
            const payload = JSON.parse(frame.data) as
              | AssistantTurnStartedEvent
              | TraceItemStartedEvent
              | TraceItemDeltaEvent
              | TraceItemCompletedEvent
              | AnswerDeltaEvent
              | TurnCompletedEvent
              | InterruptPayload<TInterrupt>
              | { message: string };

            if (frame.event === "error") {
              throw new Error((payload as { message: string }).message);
            }

            if (frame.event === "assistant_turn_started") {
              setTurns((current) => ensureAssistantTurn(current, payload as AssistantTurnStartedEvent));
              continue;
            }

            if (frame.event === "trace_item_started") {
              const event = payload as TraceItemStartedEvent;
              setTurns((current) =>
                ensureAssistantTurn(current, { turn_id: event.turn_id }).map((turn) =>
                  turn.id === event.turn_id
                    ? {
                        ...turn,
                        trace_items: upsertTraceItem(turn.trace_items ?? [], event.item),
                        collapsed: true,
                        status: "streaming",
                      }
                    : turn,
                ),
              );
              continue;
            }

            if (frame.event === "trace_item_delta") {
              const event = payload as TraceItemDeltaEvent;
              setTurns((current) =>
                current.map((turn) =>
                  turn.id === event.turn_id
                    ? {
                        ...turn,
                        trace_items: (turn.trace_items ?? []).map((item) =>
                          item.id === event.item_id
                            ? {
                                ...item,
                                text: appendTraceDelta(item.text, event.delta),
                              }
                            : item,
                        ),
                      }
                    : turn,
                ),
              );
              continue;
            }

            if (frame.event === "trace_item_completed") {
              const event = payload as TraceItemCompletedEvent;
              setTurns((current) =>
                current.map((turn) =>
                  turn.id === event.turn_id
                    ? {
                        ...turn,
                        trace_items: (turn.trace_items ?? []).map((item) =>
                          item.id === event.item_id
                            ? {
                                ...item,
                                status: "completed",
                              }
                            : item,
                        ),
                      }
                    : turn,
                ),
              );
              continue;
            }

            if (frame.event === "answer_delta") {
              const event = payload as AnswerDeltaEvent;
              setTurns((current) =>
                ensureAssistantTurn(current, { turn_id: event.turn_id }).map((turn) =>
                  turn.id === event.turn_id
                    ? {
                        ...turn,
                        answer_text: `${turn.answer_text ?? ""}${event.delta}`,
                        status: "streaming",
                      }
                    : turn,
                ),
              );
              continue;
            }

            if (frame.event === "turn_completed") {
              const event = payload as TurnCompletedEvent;
              setTurns((current) =>
                current.map((turn) =>
                  turn.id === event.turn_id
                    ? {
                        ...turn,
                        ...event.turn,
                        status: "completed",
                        collapsed: true,
                        summary: event.summary ?? event.turn?.summary ?? turn.summary,
                        citations: event.citations ?? event.turn?.citations ?? turn.citations,
                        asset_citations: event.turn?.asset_citations ?? turn.asset_citations,
                        asset_sources: event.turn?.asset_sources ?? turn.asset_sources,
                        web_sources: event.web_sources ?? event.turn?.web_sources ?? turn.web_sources,
                        tool_sources: event.tool_sources ?? event.turn?.tool_sources ?? turn.tool_sources,
                      }
                    : turn,
                ),
              );
              continue;
            }

            if (frame.event === "interrupt") {
              setInterrupt(payload as InterruptPayload<TInterrupt>);
            }
          }
        }
      } catch (caught) {
        if (caught instanceof Error && caught.name === "AbortError") {
          return;
        }
        const nextError = caught instanceof Error ? caught : new Error("Stream failed.");
        setError(nextError);
        throw nextError;
      } finally {
        abortRef.current = null;
        submitInFlightRef.current = false;
        setIsLoading(false);
      }
    },
    [apiBaseUrl, stop, threadId],
  );

  const queueGuidance = useCallback(
    async ({
      projectId,
      threadId: targetThreadId,
      content,
      optimisticTurn,
    }: {
      projectId: string;
      threadId?: string;
      content: string;
      optimisticTurn?: ChatTurn;
    }) => {
      const normalized = content.trim();
      if (!normalized) return;
      const currentThreadId = targetThreadId || threadId;
      const response = await fetch(`${apiBaseUrl}/chat/guidance`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: projectId,
          thread_id: currentThreadId,
          content: normalized,
        }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      if (optimisticTurn) {
        setTurns((current) => [...current, optimisticTurn]);
      }
    },
    [apiBaseUrl, threadId],
  );

  return useMemo(
    () => ({
      threadId,
      turns,
      interrupt,
      isLoading,
      error,
      submit,
      queueGuidance,
      restoreSession,
      listSessions,
      deleteSession,
      stop,
      resetThread,
      toggleTurnCollapsed,
    }),
    [threadId, turns, interrupt, isLoading, error, submit, queueGuidance, restoreSession, listSessions, deleteSession, stop, resetThread, toggleTurnCollapsed],
  );
}
