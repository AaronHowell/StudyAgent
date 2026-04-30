import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import App from "./App";

// Mock react-pdf to avoid DOMMatrix issue in jsdom
vi.mock("react-pdf", () => ({
  Document: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-pdf">{children}</div>,
  Page: () => <div data-testid="mock-pdf-page" />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" }, version: "4.0.0" },
}));

vi.mock("react-pdf/dist/Page/AnnotationLayer.css", () => ({}));
vi.mock("react-pdf/dist/Page/TextLayer.css", () => ({}));

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

// Mock ChatPanel which now replaces PaperLabChatPanel in some places
vi.mock("./components/chat/ChatPanel", () => ({
  ChatPanel: ({
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

        if (url.includes("/sessions")) {
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

    expect(screen.getByRole("tab", { name: /论文工作台/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /AI 对话/ })).toBeInTheDocument();
  });

  test("可以切换到 AI 对话工作台", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: /AI 对话/ }));

    expect(screen.getByRole("tab", { name: /AI 对话/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("mock-chat-panel")).toBeInTheDocument();
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
      expect(screen.getByText("Attention Is All You Need")).toBeInTheDocument(),
    );
  });

  test("论文列表以卡片形式展示", async () => {
    localStorage.setItem(
      "paperlab.desktop.preferences",
      JSON.stringify({
        rootPath: "D:/Research/Papers",
        projectId: "vision-lab",
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Attention Is All You Need")).toBeInTheDocument(),
    );
    expect(screen.getByText("attention-is-all-you-need.pdf")).toBeInTheDocument();
  });

  test("论文列表超过单页上限时支持翻页", async () => {
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

    // First page shows 12 items
    expect(screen.getByText("论文 12")).toBeInTheDocument();
    expect(screen.queryByText("论文 13")).not.toBeInTheDocument();

    // Navigate to page 2
    const nextBtn = screen.getByTitle("下一页");
    await user.click(nextBtn);

    await waitFor(() =>
      expect(screen.getByText("论文 13")).toBeInTheDocument(),
    );
  });
});
