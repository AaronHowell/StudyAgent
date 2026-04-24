import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import App from "./App";

vi.mock("./PaperLabChatPanel", () => ({
  PaperLabChatPanel: ({
    title,
    description,
    contextLabel,
    placeholder,
  }: {
    title: string;
    description: string;
    contextLabel?: string;
    placeholder: string;
  }) => (
    <section data-testid="mock-chat-panel">
      <h3>{title}</h3>
      <p>{description}</p>
      {contextLabel ? <p>{contextLabel}</p> : null}
      <p>{placeholder}</p>
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
  ingested: false,
  modified_at: "2026-04-21T10:00:00.000Z",
  content_hash: "hash-1",
};

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);

        if (url.includes("/documents/scan")) {
          return Promise.resolve(
            new Response(JSON.stringify({ documents: [mockDocument] }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }

        if (url.includes("/documents/ingest")) {
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

  test("opens in paper workspace by default", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "Paper Workspace" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("heading", { name: "Research Desk" })).toBeInTheDocument();
  });

  test("switches to AI workspace from the app tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "AI Workspace" }));

    expect(screen.getByRole("tab", { name: "AI Workspace" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("heading", { name: "AI Research Console" })).toBeInTheDocument();
  });

  test("shows visible document actions after scanning a paper", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Scan Papers" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Open Reader" })).toBeInTheDocument(),
    );

    expect(screen.getByRole("button", { name: "Figure Gallery" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ingest Paper" })).toBeInTheDocument();
  });
});
