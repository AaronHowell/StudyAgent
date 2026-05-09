import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { ChatMessage } from "./ChatMessage";
import type { ChatTurn } from "../../usePaperLabStream";

describe("ChatMessage", () => {
  test("does not render image citations in the footer and hides inline-referenced asset cards", () => {
    const turn: ChatTurn = {
      id: "turn-1",
      role: "assistant",
      answer_text: "这里先解释图表。\n\n<ref pic>A1</ref pic>\n\n正文继续。",
      citations: [
        {
          document_id: "doc-1",
          document_title: "Tracking Patches for Open Source Software Vulnerabilities",
          chunk_id: "chunk-1",
          page: 18,
          locator: "p.18",
        },
      ],
      asset_citations: [
        {
          asset_id: "asset-1",
          document_id: "doc-1",
          document_title: "Tracking Patches for Open Source Software Vulnerabilities",
          label: "Table 8",
          page: 18,
          locator: "p.18",
        },
      ],
      asset_sources: [
        {
          ref_id: "A1",
          asset_id: "asset-1",
          document_id: "doc-1",
          page_number: 18,
          asset_label: "Table 8",
          summary: "Dependency resolution time vs. skill count.",
          file_url: "/api/assets/asset-1.png",
        },
      ],
      trace_items: [],
      summary: { done: "", next: "", pending: "" },
    };

    const { container } = render(
      <ChatMessage turn={turn} showSummary={false} onToggleTrace={() => undefined} />,
    );

    expect(
      screen.getByText("Tracking Patches for Open Source Software Vulnerabilities p.18"),
    ).toBeInTheDocument();
    expect(container.querySelector(".citation-row")?.textContent).not.toContain("Table 8");
    expect(container.querySelector(".asset-grid")).toBeNull();
    expect(screen.getAllByText("Table 8")).toHaveLength(1);
  });

  test("dedupes near-duplicate asset cards and prefers semantic labels over raw filenames", () => {
    const turn: ChatTurn = {
      id: "turn-2",
      role: "assistant",
      answer_text: "你可以通过查看资产了解图表内容。",
      citations: [],
      asset_citations: [],
      asset_sources: [
        {
          ref_id: "A1",
          asset_id: "asset-1",
          document_id: "doc-1",
          page_number: 3,
          asset_label: "Figure 1",
          summary: "Figure 1 shows the overlap between two databases DB_A and DB_B in terms of CVEs and patches.",
          file_url: "/api/assets/asset-1.png",
        },
        {
          ref_id: "A2",
          asset_id: "asset-2",
          document_id: "doc-1",
          page_number: 3,
          asset_label: "page_0003_asset_002_render.png",
          summary: "Fig. 1a shows the overlap of CVEs between databases DB_A and DB_B, and Fig. 1b presents the overlap of CVEs with patches.",
          file_url: "/api/assets/asset-2.png",
        },
      ],
      trace_items: [],
      summary: { done: "", next: "", pending: "" },
    };

    render(<ChatMessage turn={turn} showSummary={false} onToggleTrace={() => undefined} />);

    expect(screen.getByText("Figure 1")).toBeInTheDocument();
    expect(screen.queryByText("page_0003_asset_002_render.png")).toBeNull();
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });
});
