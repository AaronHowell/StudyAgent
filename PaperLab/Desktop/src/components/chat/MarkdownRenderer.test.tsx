import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { MarkdownRenderer } from "./MarkdownRenderer";

describe("MarkdownRenderer", () => {
  test("renders inline picture references from asset sources", () => {
    render(
      <MarkdownRenderer
        content={"The result is shown below.\n\n<ref pic>A1</ref pic>"}
        assetSources={[
          {
            ref_id: "A1",
            asset_id: "asset-1",
            document_id: "doc-1",
            page_number: 2,
            asset_label: "Figure 1",
            summary: "Result chart",
            file_url: "/documents/assets/asset-1/content",
          },
        ]}
      />,
    );

    expect(screen.getByText("The result is shown below.")).toBeInTheDocument();
    expect(screen.queryByText("<ref pic>A1</ref pic>")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Figure 1" })).toHaveAttribute(
      "src",
      "http://127.0.0.1:8000/documents/assets/asset-1/content",
    );
    expect(screen.getByText("Result chart")).toBeInTheDocument();
  });

  test("opens an image preview modal when inline picture is clicked", async () => {
    const user = userEvent.setup();
    render(
      <MarkdownRenderer
        content={"Inspect this figure.\n\n<ref pic>A1</ref pic>"}
        assetSources={[
          {
            ref_id: "A1",
            asset_id: "asset-1",
            document_id: "doc-1",
            page_number: 4,
            asset_label: "Figure 2",
            summary: "Tracer overview diagram",
            file_url: "/documents/assets/asset-1/content",
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "放大查看 Figure 2" }));

    expect(screen.getByRole("heading", { name: "Figure 2" })).toBeInTheDocument();
    expect(screen.getAllByText("p.4")).toHaveLength(2);
    expect(screen.getByRole("img", { name: "Figure 2 原图" })).toHaveAttribute(
      "src",
      "http://127.0.0.1:8000/documents/assets/asset-1/content",
    );
  });
});
