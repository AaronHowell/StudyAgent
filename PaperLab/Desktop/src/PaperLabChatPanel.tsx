import {
  AssistantRuntimeProvider,
  type AppendMessage,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAssistantState,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useState } from "react";
import { useStream } from "@langchain/react";

type CitationMeta = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  page?: number | null;
  locator?: string;
};

type WebSourceMeta = {
  url: string;
  title: string;
  snippet?: string;
  excerpt?: string;
};

type ToolSourceMeta = {
  title: string;
  url?: string;
  summary?: string;
  kind?: string;
  tool_name?: string;
};

type EvidenceCounts = {
  document_count: number;
  chunk_count: number;
  asset_count: number;
};

type StreamMessage = {
  id?: string;
  type?: string;
  role?: string;
  content: unknown;
  additional_kwargs?: Record<string, unknown>;
  response_metadata?: Record<string, unknown>;
};

type PaperLabStreamState = {
  messages: StreamMessage[];
  citations?: CitationMeta[];
  evidence_counts?: EvidenceCounts;
};

type LoopInterruptValue = {
  phase?: string;
  turn_id?: string;
  iteration_count?: number;
  question?: string;
  pending_user_messages?: number;
  retrieve_result_status?: string;
  tool_result_status?: string;
};

type LoopEvent = {
  id: string;
  phase: string;
  summary: string;
  artifactType: string;
  iterationCount: number;
};

type PaperLabChatPanelProps = {
  projectId: string;
  title: string;
  description: string;
  placeholder: string;
  contextLabel?: string;
  compact?: boolean;
};

const apiBase =
  import.meta.env.VITE_PAPERLAB_API_BASE_URL ?? "http://127.0.0.1:8000";
const langgraphApiUrl =
  import.meta.env.VITE_PAPERLAB_LANGGRAPH_API_URL ?? "http://127.0.0.1:2024";
const langgraphAssistantId =
  import.meta.env.VITE_PAPERLAB_LANGGRAPH_ASSISTANT_ID ?? "paperlab";

export function PaperLabChatPanel({
  projectId,
  title,
  description,
  placeholder,
  contextLabel = "",
  compact = false,
}: PaperLabChatPanelProps) {
  const [interventionDraft, setInterventionDraft] = useState("");
  const stream = useStream<PaperLabStreamState, { InterruptType: LoopInterruptValue }>({
    assistantId: langgraphAssistantId,
    apiUrl: langgraphApiUrl,
    reconnectOnMount: true,
    fetchStateHistory: true,
    initialValues: {
      messages: [],
      evidence_counts: {
        document_count: 0,
        chunk_count: 0,
        asset_count: 0,
      },
    },
  });

  const visibleMessages = dedupeVisibleMessages(
    stream.messages.filter((message) => !isToolMessage(message)),
  );
  const evidenceCounts = deriveEvidenceCounts(stream.messages, stream.values.evidence_counts);
  const loopEvents = deriveLoopEvents(stream.messages);
  const currentInterrupt = stream.interrupt?.value;

  const submitIntervention = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    await stream.submit(null, {
      command: {
        update: {
          messages: [
            {
              type: "human",
              content: trimmed,
            },
          ],
        },
        resume: { action: "continue_with_guidance" },
      },
      config: {
        configurable: {
          project_id: projectId,
        },
      },
    });
  };

  const runtime = useExternalStoreRuntime<StreamMessage>({
    isRunning: stream.isLoading,
    messages: visibleMessages,
    state: {
      evidence_counts: evidenceCounts ?? null,
    },
    onCancel: async () => {
      stream.stop();
    },
    onNew: async (message) => {
      const text = readComposerMessageText(message).trim();
      if (!text) {
        return;
      }
      if (stream.interrupt) {
        await submitIntervention(text);
        return;
      }
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
          config: {
            configurable: {
              project_id: projectId,
            },
          },
        },
      );
    },
    convertMessage: toThreadMessageLike,
  });

  const statusText = stream.isLoading ? "Streaming" : "Idle";

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className={`agent-panel ${compact ? "compact" : "regular"}`}>
        <header className="agent-panel-header">
          <div>
            <strong>{title}</strong>
            <p>{description}</p>
          </div>
          <div className="agent-panel-actions">
            <span className="chip">{statusText}</span>
            <button className="button subtle" onClick={() => stream.switchThread(null)}>
              New Thread
            </button>
          </div>
        </header>

        <div className="agent-panel-meta">
          <span className="chip">Project: {projectId}</span>
          {contextLabel ? <span className="chip">{contextLabel}</span> : null}
          <span className="chip">
            Evidence {evidenceCounts?.document_count ?? 0}/{evidenceCounts?.chunk_count ?? 0}/
            {evidenceCounts?.asset_count ?? 0}
          </span>
        </div>

        {stream.error ? (
          <p className="error-message">
            {stream.error instanceof Error ? stream.error.message : "LangGraph stream failed."}
          </p>
        ) : null}

        {loopEvents.length ? (
          <section className="agent-loop-panel">
            <div className="agent-loop-panel-header">
              <strong>Agent Loop</strong>
              <span className="chip">{loopEvents.length} events</span>
            </div>
            <div className="agent-loop-timeline">
              {loopEvents.map((event) => (
                <div className="agent-loop-event" key={event.id}>
                  <span className="chip loop-phase-chip">{event.phase}</span>
                  <div>
                    <strong>{event.summary}</strong>
                    <p>
                      {event.artifactType} · iteration {event.iterationCount}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {stream.interrupt ? (
          <section className="agent-interrupt-panel">
            <div className="agent-interrupt-copy">
              <strong>Loop paused at {currentInterrupt?.phase ?? "checkpoint"}</strong>
              <p>
                The backend reached a GuidanceGate. You can continue directly, or send a guidance
                message below and it will be injected into the current run.
              </p>
              {currentInterrupt?.question ? <p>Current question: {currentInterrupt.question}</p> : null}
            </div>
            <div className="agent-interrupt-actions">
              <button
                className="button subtle"
                onClick={() =>
                  void stream.submit(null, {
                    command: { resume: { action: "continue" } },
                    config: {
                      configurable: {
                        project_id: projectId,
                      },
                    },
                  })
                }
              >
                Continue
              </button>
            </div>
            <div className="agent-interrupt-compose">
              <textarea
                className="input textarea"
                rows={3}
                placeholder="Inject guidance into the current loop run"
                value={interventionDraft}
                onChange={(event) => setInterventionDraft(event.target.value)}
              />
              <button
                className="button primary"
                onClick={async () => {
                  await submitIntervention(interventionDraft);
                  setInterventionDraft("");
                }}
              >
                Inject Guidance
              </button>
            </div>
          </section>
        ) : null}

        <ThreadPrimitive.Root className="agent-thread-root">
          <ThreadPrimitive.If empty>
            <div className="chat-empty">
              Agent is ready. Start a grounded question and the thread will stream from LangGraph.
            </div>
          </ThreadPrimitive.If>

          <ThreadPrimitive.Viewport className="agent-thread-viewport">
            <ThreadPrimitive.Messages
              components={{
                UserMessage: UserMessageCard,
                AssistantMessage: AssistantMessageCard,
              }}
            />
          </ThreadPrimitive.Viewport>

          <ThreadPrimitive.ViewportFooter className="agent-thread-footer">
            <ComposerPrimitive.Root className="agent-composer">
              <ComposerPrimitive.Input
                className="input textarea agent-composer-input"
                rows={compact ? 4 : 6}
                autoFocus
                placeholder={placeholder}
              />
              <div className="agent-composer-actions">
                <ComposerPrimitive.Cancel className="button subtle">
                  Stop
                </ComposerPrimitive.Cancel>
                <ComposerPrimitive.Send className="button primary">
                  Send
                </ComposerPrimitive.Send>
              </div>
            </ComposerPrimitive.Root>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Root>
      </section>
    </AssistantRuntimeProvider>
  );
}

function UserMessageCard() {
  return (
    <MessagePrimitive.Root className="agent-message user">
      <div className="agent-message-label">You</div>
      <div className="agent-message-body">
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessageCard() {
  const citations = useAssistantState(({ message }) => {
    const custom = message.metadata?.custom as { citations?: CitationMeta[] } | undefined;
    return custom?.citations ?? [];
  });
  const webSources = useAssistantState(({ message }) => {
    const custom = message.metadata?.custom as { webSources?: WebSourceMeta[] } | undefined;
    return custom?.webSources ?? [];
  });
  const toolSources = useAssistantState(({ message }) => {
    const custom = message.metadata?.custom as { toolSources?: ToolSourceMeta[] } | undefined;
    return custom?.toolSources ?? [];
  });

  return (
    <MessagePrimitive.Root className="agent-message assistant">
      <div className="agent-message-label">PaperLab</div>
      <div className="agent-message-body">
        <MessagePrimitive.Content />
        {citations.length ? (
          <div className="citation-row">
            {citations.map((citation) => (
              <span className="chip citation-chip" key={`${citation.chunk_id}-${citation.locator ?? citation.page ?? "source"}`}>
                {citation.document_title} {citation.locator ?? (citation.page ? `p.${citation.page}` : "")}
              </span>
            ))}
          </div>
        ) : null}
        {webSources.length ? (
          <div className="citation-row">
            {webSources.map((source) => (
              <a
                className="chip citation-chip"
                key={source.url}
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                {source.title || source.url}
              </a>
            ))}
          </div>
        ) : null}
        {toolSources.length ? (
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
                  {source.title || source.tool_name || "Tool source"}
                </a>
              ) : (
                <span className="chip citation-chip" key={`${source.title}-${index}`}>
                  {source.title || source.tool_name || "Tool source"}
                </span>
              ),
            )}
          </div>
        ) : null}
      </div>
    </MessagePrimitive.Root>
  );
}

function readComposerMessageText(message: AppendMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n\n");
}

function toThreadMessageLike(message: StreamMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: normalizeRole(message),
    content: normalizeContent(message.content),
    metadata: {
      custom: {
        citations: extractCitations(message),
        webSources: extractWebSources(message),
        toolSources: extractToolSources(message),
      },
    },
  };
}

function normalizeRole(message: StreamMessage): ThreadMessageLike["role"] {
  const role = message.type ?? message.role ?? "assistant";
  if (role === "human" || role === "user") {
    return "user";
  }
  if (role === "system") {
    return "system";
  }
  return "assistant";
}

function normalizeContent(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") {
          return part;
        }
        if (typeof part === "object" && part && "text" in part) {
          return String((part as { text?: unknown }).text ?? "");
        }
        return "";
      })
      .join("");
  }
  return String(content ?? "");
}

function extractCitations(message: StreamMessage): CitationMeta[] {
  const candidate =
    readMessageMetadata(message).citations ??
    message.response_metadata?.citations ??
    message.additional_kwargs?.citations ??
    [];
  if (!Array.isArray(candidate)) {
    return [];
  }
  return candidate
    .filter((item): item is CitationMeta => typeof item === "object" && item !== null)
    .map((item) => ({
      document_id: String(item.document_id ?? ""),
      document_title: String(item.document_title ?? ""),
      chunk_id: String(item.chunk_id ?? ""),
      page:
        typeof item.page === "number" || item.page == null
          ? item.page
          : Number(item.page),
      locator: typeof item.locator === "string" ? item.locator : "",
    }));
}

function extractWebSources(message: StreamMessage): WebSourceMeta[] {
  const candidate = readMessageMetadata(message).web_sources ?? [];
  if (!Array.isArray(candidate)) {
    return [];
  }
  return candidate
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => ({
      url: String(item.url ?? ""),
      title: String(item.title ?? ""),
      snippet: typeof item.snippet === "string" ? item.snippet : "",
      excerpt: typeof item.excerpt === "string" ? item.excerpt : "",
    }))
    .filter((item) => Boolean(item.url));
}

function extractToolSources(message: StreamMessage): ToolSourceMeta[] {
  const candidate = readMessageMetadata(message).tool_sources ?? [];
  if (!Array.isArray(candidate)) {
    return [];
  }
  return candidate
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => ({
      title: String(item.title ?? ""),
      url: typeof item.url === "string" ? item.url : "",
      summary: typeof item.summary === "string" ? item.summary : "",
      kind: typeof item.kind === "string" ? item.kind : "",
      tool_name: typeof item.tool_name === "string" ? item.tool_name : "",
    }));
}

function isToolMessage(message: StreamMessage): boolean {
  return (message.type ?? message.role ?? "") === "tool";
}

function readMessageMetadata(message: StreamMessage): Record<string, unknown> {
  const additional = message.additional_kwargs;
  if (
    additional &&
    typeof additional === "object" &&
    "metadata" in additional &&
    typeof additional.metadata === "object" &&
    additional.metadata !== null
  ) {
    return additional.metadata as Record<string, unknown>;
  }
  if (message.response_metadata && typeof message.response_metadata === "object") {
    return message.response_metadata;
  }
  return {};
}

function deriveEvidenceCounts(
  messages: StreamMessage[],
  fallback: EvidenceCounts | undefined,
): EvidenceCounts | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const metadata = readMessageMetadata(messages[index]);
    const candidate = metadata.evidence_counts;
    if (
      candidate &&
      typeof candidate === "object" &&
      candidate !== null &&
      "document_count" in candidate &&
      "chunk_count" in candidate &&
      "asset_count" in candidate
    ) {
      return {
        document_count: Number(candidate.document_count ?? 0),
        chunk_count: Number(candidate.chunk_count ?? 0),
        asset_count: Number(candidate.asset_count ?? 0),
      };
    }
  }
  return fallback;
}

function dedupeVisibleMessages(messages: StreamMessage[]): StreamMessage[] {
  const deduped: StreamMessage[] = [];
  for (const message of messages) {
    const previous = deduped[deduped.length - 1];
    if (
      previous &&
      normalizeRole(previous) === "user" &&
      normalizeRole(message) === "user" &&
      normalizeContent(previous.content) === normalizeContent(message.content)
    ) {
      const previousStructured = readMessageMetadata(previous).artifact_type === "question";
      const currentStructured = readMessageMetadata(message).artifact_type === "question";
      if (!previousStructured && currentStructured) {
        deduped[deduped.length - 1] = message;
        continue;
      }
      if (previousStructured && !currentStructured) {
        continue;
      }
    }
    deduped.push(message);
  }
  return deduped;
}

function deriveLoopEvents(messages: StreamMessage[]): LoopEvent[] {
  return messages
    .filter((message) => isToolMessage(message))
    .map((message, index) => {
      const metadata = readMessageMetadata(message);
      const artifactType = String(metadata.artifact_type ?? "");
      if (!["loop_status", "agent_task", "agent_result"].includes(artifactType)) {
        return null;
      }
      return {
        id: String(message.id ?? `${artifactType}-${index}`),
        phase: String(metadata.phase ?? artifactType),
        summary: normalizeContent(message.content),
        artifactType,
        iterationCount: Number(metadata.iteration_count ?? 0),
      } satisfies LoopEvent;
    })
    .filter((event): event is LoopEvent => event !== null);
}

export function buildDocumentFileUrl(path: string): string {
  return `${apiBase}/documents/file?path=${encodeURIComponent(path)}`;
}
