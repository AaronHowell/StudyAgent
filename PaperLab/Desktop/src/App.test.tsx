import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import App from "./App";

vi.mock("./PaperLabChatPanel", () => ({
  PaperLabChatPanel: ({
    title,
    contextLabel,
  }: {
    title: string;
    contextLabel?: string;
  }) => (
    <section data-testid="mock-chat-panel">
      <h3>{title}</h3>
      {contextLabel ? <p>{contextLabel}</p> : null}
    </section>
  ),
  buildDocumentFileUrl: (path: string) => `mock://${path}`,
}));

const mockDocument = {
  id: "doc-1",
  title: "Attention Is All You Need",
  file_name: "attention-is-all-you-need.pdf",
  path: "C:/papers/attention-is-all-you-need.pdf",
  doc_type: "paper",
  status: "ready",
  ingested: true,
  modified_at: "2026-04-21T10:00:00.000Z",
  content_hash: "hash-1",
};

let scannedDocuments = [mockDocument];

function buildMockDocument(index: number) {
  return {
    id: `doc-${index}`,
    title: `论文 ${index}`,
    file_name: `paper-${index}.pdf`,
    path: `C:/papers/paper-${index}.pdf`,
    doc_type: "paper",
    status: "ready",
    ingested: index % 2 === 0,
    modified_at: `2026-04-${String((index % 28) + 1).padStart(2, "0")}T10:00:00.000Z`,
    content_hash: `hash-${index}`,
  };
}

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    scannedDocuments = [mockDocument];

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.includes("/documents/scan")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                root_path: JSON.parse(String(init?.body)).root_path,
                documents: scannedDocuments,
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }

        if (url.endsWith("/documents/ingest")) {
          return Promise.resolve(
            new Response(JSON.stringify([]), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        return Promise.resolve(
          new Response(JSON.stringify({ images: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
  });

  test("默认进入论文工作台", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "论文工作台" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "论文工作台" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "最近入库任务" })).not.toBeInTheDocument();
  });

  test("可以切换到 AI 对话工作台", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "AI 对话" }));

    expect(screen.getByRole("tab", { name: "AI 对话" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("左侧按项目和历史对话组织，右侧专注当前对话内容。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "调整项目" })).toBeInTheDocument();
  });

  test("启动时恢复上次项目并自动刷新论文列表", async () => {
    localStorage.setItem(
      "paperlab.desktop.preferences",
      JSON.stringify({
        rootPath: "D:/Research/Papers",
        projectId: "vision-lab",
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByLabelText("项目目录")).toHaveValue("D:/Research/Papers"),
    );
    expect(screen.getByLabelText("项目 ID")).toHaveValue("vision-lab");

    await waitFor(() =>
      expect(screen.getByText("Attention Is All You Need")).toBeInTheDocument(),
    );
  });

  test("选择文件夹接口不存在时显示可读错误", async () => {
    const user = userEvent.setup();

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);

        if (url.includes("/desktop/project-folder/select")) {
          return Promise.resolve(
            new Response(JSON.stringify({ detail: "Not Found" }), {
              status: 404,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/documents/scan")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                root_path: JSON.parse(String(init?.body)).root_path,
                documents: [mockDocument],
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }

        if (url.endsWith("/documents/ingest")) {
          return Promise.resolve(
            new Response(JSON.stringify([]), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        return Promise.resolve(
          new Response(JSON.stringify({ images: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("button", { name: "选择文件夹" }));

    await waitFor(() =>
      expect(screen.getByText("项目目录选择接口不可用，请重启后端到最新版本后重试。")).toBeInTheDocument(),
    );
  });

  test("论文列表超过单页上限时只显示当前页，并支持翻页", async () => {
    const user = userEvent.setup();
    scannedDocuments = Array.from({ length: 13 }, (_, index) => buildMockDocument(index + 1));
    localStorage.setItem(
      "paperlab.desktop.preferences",
      JSON.stringify({
        rootPath: "D:/Research/Papers",
        projectId: "vision-lab",
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("论文 1")).toBeInTheDocument(),
    );

    expect(screen.getByText("论文 10")).toBeInTheDocument();
    expect(screen.queryByText("论文 11")).not.toBeInTheDocument();
    expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(screen.getByText("论文 11")).toBeInTheDocument();
    expect(screen.getByText("论文 13")).toBeInTheDocument();
    expect(screen.queryByText("论文 1")).not.toBeInTheDocument();
    expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument();
  });
});
