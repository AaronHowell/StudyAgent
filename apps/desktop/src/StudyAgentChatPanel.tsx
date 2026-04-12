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
import { useStream } from "@langchain/react";

type CitationMeta = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  page?: number | null;
  locator?: string;
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

type StudyAgentStreamState = {
  messages: StreamMessage[];
  citations?: CitationMeta[];
  evidence_counts?: EvidenceCounts;
};

type StudyAgentChatPanelProps = {
  projectId: string;
  title: string;
  description: string;
  placeholder: string;
  contextLabel?: string;
  compact?: boolean;
};

const apiBase =
  import.meta.env.VITE_STUDY_AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";
const langgraphApiUrl =
  import.meta.env.VITE_STUDY_AGENT_LANGGRAPH_API_URL ?? "http://127.0.0.1:2024";
const langgraphAssistantId =
  import.meta.env.VITE_STUDY_AGENT_LANGGRAPH_ASSISTANT_ID ?? "study_agent";

export function StudyAgentChatPanel({
  projectId,
  title,
  description,
  placeholder,
  contextLabel = "",
  compact = false,
}: StudyAgentChatPanelProps) {
  const stream = useStream<StudyAgentStreamState>({
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

  const runtime = useExternalStoreRuntime<StreamMessage>({
    isRunning: stream.isLoading,
    messages: stream.messages,
    state: {
      evidence_counts: stream.values.evidence_counts ?? null,
    },
    onCancel: async () => {
      stream.stop();
    },
    onNew: async (message) => {
      const text = readComposerMessageText(message).trim();
      if (!text) {
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

  const evidenceCounts = stream.values.evidence_counts;
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

  return (
    <MessagePrimitive.Root className="agent-message assistant">
      <div className="agent-message-label">StudyAgent</div>
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
    message.response_metadata?.citations ?? message.additional_kwargs?.citations ?? [];
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

export function buildDocumentFileUrl(path: string): string {
  return `${apiBase}/documents/file?path=${encodeURIComponent(path)}`;
}
