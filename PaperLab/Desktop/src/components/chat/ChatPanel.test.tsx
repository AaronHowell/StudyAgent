import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";

function createSseResponse(frames: Array<{ event: string; data: object }>) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(
          encoder.encode(`event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`),
        );
      }
      controller.close();
    },
  });

  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/sessions?")) {
          return Promise.resolve(
            new Response(JSON.stringify([]), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          createSseResponse([
            {
              event: "assistant_turn_started",
              data: { turn_id: "turn-1", created_at: "2026-05-08T10:00:00Z" },
            },
            {
              event: "answer_delta",
              data: { turn_id: "turn-1", delta: "你好。" },
            },
            {
              event: "turn_completed",
              data: { turn_id: "turn-1", summary: { done: "", next: "", pending: "" } },
            },
          ]),
        );
      }),
    );
  });

  test("renders tool toggle and submits tools_enabled=true when enabled", async () => {
    const user = userEvent.setup();

    render(
      <ChatPanel
        projectId="default-project"
        title="AI 对话"
        description="测试"
        placeholder="输入问题"
      />,
    );

    await user.click(screen.getByLabelText("工具"));
    await user.type(screen.getByPlaceholderText("输入问题"), "你好");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const streamCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).includes("/chat/stream"));

    expect(streamCall).toBeTruthy();
    expect(JSON.parse(String((streamCall?.[1] as RequestInit | undefined)?.body))).toMatchObject({
      tools_enabled: true,
    });

    await waitFor(() => expect(screen.getByText("你好。")).toBeInTheDocument());
  });
});
