import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type StreamMessage = {
  id?: string;
  type?: string;
  role?: string;
  content: unknown;
  additional_kwargs?: Record<string, unknown>;
  response_metadata?: Record<string, unknown>;
};

type InterruptPayload<TInterrupt> = {
  id: string;
  value: TInterrupt;
};

type ChatStatePayload<TInterrupt> = {
  thread_id: string;
  project_id: string;
  messages: StreamMessage[];
  interrupt: InterruptPayload<TInterrupt> | null;
  next_nodes?: string[];
};

type SubmitOptions = {
  command?: {
    update?: {
      messages?: Array<{ type: string; content: string }>;
    };
    resume?: Record<string, unknown>;
  };
  config?: {
    configurable?: {
      project_id?: string;
      thread_id?: string;
    };
  };
};

type StreamSubmitInput = {
  messages: Array<{ type: string; content: string }>;
} | null;

type UsePaperLabStreamOptions<TValues, TInterrupt> = {
  apiBaseUrl: string;
  initialValues: TValues;
};

type UsePaperLabStreamResult<TValues, TInterrupt> = {
  threadId: string;
  messages: StreamMessage[];
  values: TValues;
  interrupt: InterruptPayload<TInterrupt> | null;
  isLoading: boolean;
  error: Error | null;
  submit: (input: StreamSubmitInput, options?: SubmitOptions) => Promise<void>;
  stop: () => void;
  switchThread: (threadId: string | null) => void;
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

export function usePaperLabStream<
  TValues extends { messages?: StreamMessage[] },
  TInterrupt extends Record<string, unknown>,
>({
  apiBaseUrl,
  initialValues,
}: UsePaperLabStreamOptions<TValues, TInterrupt>): UsePaperLabStreamResult<TValues, TInterrupt> {
  const initialValuesRef = useRef(initialValues);
  const [threadId, setThreadId] = useState(createThreadId);
  const [messages, setMessages] = useState<StreamMessage[]>([]);
  const [values, setValues] = useState<TValues>(initialValues);
  const [interrupt, setInterrupt] = useState<InterruptPayload<TInterrupt> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
  }, []);

  const switchThread = useCallback((nextThreadId: string | null) => {
    stop();
    setError(null);
    setInterrupt(null);
    setMessages([]);
    setValues(initialValuesRef.current);
    setThreadId(nextThreadId || createThreadId());
  }, [stop]);

  const submit = useCallback(
    async (input: StreamSubmitInput, options?: SubmitOptions) => {
      stop();
      setError(null);
      setIsLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;
      const currentThreadId = options?.config?.configurable?.thread_id || threadId;
      const projectId = options?.config?.configurable?.project_id;
      if (!projectId) {
        setIsLoading(false);
        throw new Error("project_id is required for PaperLab chat.");
      }
      setThreadId(currentThreadId);

      const response = await fetch(`${apiBaseUrl}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          thread_id: currentThreadId,
          project_id: projectId,
          input,
          command: options?.command,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        setIsLoading(false);
        throw new Error(await response.text());
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
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
            const payload = JSON.parse(frame.data) as ChatStatePayload<TInterrupt> | { message: string };
            if (frame.event === "error") {
              throw new Error((payload as { message: string }).message);
            }
            if (frame.event === "state" || frame.event === "done") {
              const statePayload = payload as ChatStatePayload<TInterrupt>;
              setMessages(statePayload.messages ?? []);
              setValues((current) => ({
                ...current,
                messages: statePayload.messages ?? [],
              }));
              setInterrupt(statePayload.interrupt ?? null);
            }
          }
        }
      } finally {
        abortRef.current = null;
        setIsLoading(false);
      }
    },
    [apiBaseUrl, stop, threadId],
  );

  useEffect(() => {
    initialValuesRef.current = initialValues;
  }, [initialValues]);

  useEffect(() => {
    setMessages([]);
    setValues(initialValuesRef.current);
    setInterrupt(null);
  }, [threadId]);

  return useMemo(
    () => ({
      threadId,
      messages,
      values,
      interrupt,
      isLoading,
      error,
      submit,
      stop,
      switchThread,
    }),
    [threadId, messages, values, interrupt, isLoading, error, submit, stop, switchThread],
  );
}
