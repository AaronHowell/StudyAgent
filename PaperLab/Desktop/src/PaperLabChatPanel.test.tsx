import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { PaperLabChatPanel } from "./PaperLabChatPanel";

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

describe("PaperLabChatPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/sessions?")) {
          return Promise.resolve(
            new Response(
              JSON.stringify([
                {
                  session_id: "thread-1",
                  title: "解释这篇论文的核心贡献",
                  project_id: "vision-lab",
                  updated_at: "2026-04-22T10:00:00Z",
                  message_count: 2,
                  resume_capable: false,
                },
              ]),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (url.includes("/sessions/thread-1/snapshot?")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                session_id: "thread-1",
                thread_id: "thread-1",
                project_id: "vision-lab",
                interrupt: null,
                turns: [
                  {
                    id: "user-turn-1",
                    role: "user",
                    content: "解释这篇论文的核心贡献",
                    created_at: "2026-04-22T10:00:00Z",
                  },
                  {
                    id: "turn-1",
                    role: "assistant",
                    answer_text: "这篇论文的核心贡献是提出纯注意力架构。",
                    status: "completed",
                    collapsed: true,
                    created_at: "2026-04-22T10:00:01Z",
                    summary: {
                      done: "已总结论文核心贡献",
                      next: "可以继续追问方法细节",
                      pending: "尚未比较相关工作",
                    },
                    citations: [
                      {
                        document_id: "doc-1",
                        document_title: "Attention Is All You Need",
                        chunk_id: "chunk-1",
                        page: 3,
                        locator: "p.3",
                      },
                    ],
                    trace_items: [
                      {
                        id: "trace-1",
                        kind: "reasoning",
                        title: "思考",
                        text: "先总结问题，再查找核心贡献。",
                        status: "completed",
                      },
                      {
                        id: "trace-2",
                        kind: "tool_call",
                        title: "retrieval_agent",
                        text: "检索论文核心段落",
                        status: "completed",
                      },
                    ],
                  },
                ],
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }
        if (url.includes("/chat/guidance")) {
          return Promise.resolve(
            new Response(JSON.stringify({ queued: true }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        return Promise.resolve(
          createSseResponse([
            {
              event: "assistant_turn_started",
              data: {
                turn_id: "turn-2",
                created_at: "2026-04-22T10:02:00Z",
              },
            },
            {
              event: "trace_item_started",
              data: {
                turn_id: "turn-2",
                item: {
                  id: "trace-a",
                  kind: "reasoning",
                  title: "思考",
                  text: "",
                  status: "streaming",
                },
              },
            },
            {
              event: "trace_item_delta",
              data: {
                turn_id: "turn-2",
                item_id: "trace-a",
                delta: "先检索，再总结核心贡献。",
              },
            },
            {
              event: "trace_item_completed",
              data: {
                turn_id: "turn-2",
                item_id: "trace-a",
              },
            },
            {
              event: "trace_item_started",
              data: {
                turn_id: "turn-2",
                item: {
                  id: "trace-b",
                  kind: "tool_call",
                  title: "retrieval_agent",
                  text: "",
                  status: "streaming",
                },
              },
            },
            {
              event: "trace_item_delta",
              data: {
                turn_id: "turn-2",
                item_id: "trace-b",
                delta: "检索论文核心段落",
              },
            },
            {
              event: "trace_item_completed",
              data: {
                turn_id: "turn-2",
                item_id: "trace-b",
              },
            },
            {
              event: "answer_delta",
              data: {
                turn_id: "turn-2",
                delta: "这篇论文的核心贡献是提出纯注意力架构。",
              },
            },
            {
              event: "turn_completed",
              data: {
                turn_id: "turn-2",
                summary: {
                  done: "已总结论文核心贡献",
                  next: "",
                  pending: "",
                },
                citations: [
                  {
                    document_id: "doc-1",
                    document_title: "Attention Is All You Need",
                    chunk_id: "chunk-1",
                    page: 3,
                    locator: "p.3",
                  },
                ],
              },
            },
          ]),
        );
      }),
    );
  });

  test("启动时从 snapshot 恢复历史 turn，并默认折叠思考轨道", async () => {
    const user = userEvent.setup();

    render(
      <PaperLabChatPanel
        projectId="vision-lab"
        title="论文助手"
        description="测试用聊天面板"
        placeholder="请输入问题"
        showThreadSidebar
      />,
    );

    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/sessions/thread-1/snapshot?project_id=vision-lab"),
      ),
    );

    expect(await screen.findByText("这篇论文的核心贡献是提出纯注意力架构。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "已完成思考" })).toBeInTheDocument();
    expect(screen.queryByText("先总结问题，再查找核心贡献。")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "已完成思考" }));

    expect(screen.getByText("先总结问题，再查找核心贡献。")).toBeInTheDocument();
    expect(screen.getByText("检索论文核心段落")).toBeInTheDocument();
  });

  test("发送后按事件流组装 trace 和正文，并在完成后自动折叠", async () => {
    const user = userEvent.setup();

    render(
      <PaperLabChatPanel
        projectId="vision-lab"
        title="论文助手"
        description="测试用聊天面板"
        placeholder="请输入问题"
      />,
    );

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByLabelText("工具"));
    await user.type(screen.getByPlaceholderText("请输入问题"), "解释这篇论文的核心贡献");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const streamCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => String(input).includes("/chat/stream"));
    expect(JSON.parse(String((streamCall?.[1] as RequestInit | undefined)?.body))).toMatchObject({
      tools_enabled: true,
    });

    expect(screen.getByText("解释这篇论文的核心贡献")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("这篇论文的核心贡献是提出纯注意力架构。")).toBeInTheDocument(),
    );

    expect(screen.getByRole("button", { name: "已完成思考" })).toBeInTheDocument();
    expect(screen.queryByText("先检索，再总结核心贡献。")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "已完成思考" }));

    expect(screen.getByText("先检索，再总结核心贡献。")).toBeInTheDocument();
    expect(screen.getByText("检索论文核心段落")).toBeInTheDocument();
    expect(screen.getByText("Attention Is All You Need p.3")).toBeInTheDocument();
  });

  test("流式回答中输入会进入引导队列而不是启动新对话", async () => {
    const user = userEvent.setup();
    const streamControllers: Array<ReadableStreamDefaultController<Uint8Array>> = [];
    const encoder = new TextEncoder();
    vi.mocked(globalThis.fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/sessions?")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (url.includes("/chat/guidance")) {
        return Promise.resolve(new Response(JSON.stringify({ queued: true }), { status: 200 }));
      }
      if (url.includes("/chat/stream")) {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            streamControllers.push(controller);
            controller.enqueue(
              encoder.encode(
                `event: assistant_turn_started\ndata: ${JSON.stringify({ turn_id: "turn-2" })}\n\n`,
              ),
            );
          },
        });
        return Promise.resolve(new Response(body, { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(
      <PaperLabChatPanel
        projectId="vision-lab"
        title="论文助手"
        description="测试用聊天面板"
        placeholder="请输入问题"
      />,
    );

    await user.type(screen.getByPlaceholderText("请输入问题"), "解释论文");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await user.type(screen.getByPlaceholderText("请输入问题"), "请优先看实验");
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/chat/guidance"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("请优先看实验"),
        }),
      ),
    );
    expect(screen.getByText("请优先看实验")).toBeInTheDocument();
    streamControllers[0]?.close();
  });
});
