import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { AgentTrace } from "./AgentTrace";

describe("AgentTrace", () => {
  test("hides trace section when all items are low-signal workflow checkpoints", () => {
    render(
      <AgentTrace
        items={[
          {
            id: "t1",
            kind: "reasoning",
            title: "guidance_gate_pre_route",
            text: "Loop checkpoint reached at guidance_gate_pre_route.",
            status: "completed",
          },
          {
            id: "t2",
            kind: "reasoning",
            title: "parallel_specialists_complete",
            text: "Parallel specialist execution finished.",
            status: "completed",
          },
        ]}
        status="completed"
        collapsed={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByText("已完成思考")).not.toBeInTheDocument();
    expect(screen.queryByText("收起思考")).not.toBeInTheDocument();
  });

  test("keeps meaningful retrieval items visible", () => {
    render(
      <AgentTrace
        items={[
          {
            id: "t1",
            kind: "reasoning",
            title: "guidance_gate_pre_route",
            text: "Loop checkpoint reached at guidance_gate_pre_route.",
            status: "completed",
          },
          {
            id: "t2",
            kind: "tool_call",
            title: "retrieval_agent",
            text: "retrieval_agent task: 列出论文标题",
            status: "completed",
          },
        ]}
        status="completed"
        collapsed={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("retrieval_agent")).toBeInTheDocument();
    expect(screen.queryByText("guidance_gate_pre_route")).not.toBeInTheDocument();
  });

  test("applies memory category class to memory trace cards", () => {
    const { container } = render(
      <AgentTrace
        items={[
          {
            id: "m1",
            kind: "reasoning",
            title: "长期记忆检索",
            text: "Relevant memory:\n- AaronHowell",
            status: "completed",
          },
        ]}
        status="completed"
        collapsed={false}
        onToggle={vi.fn()}
      />,
    );

    expect(container.querySelector(".trace-item-memory")).not.toBeNull();
  });

  test("applies retrieval category class to retrieval trace cards", () => {
    const { container } = render(
      <AgentTrace
        items={[
          {
            id: "r1",
            kind: "tool_call",
            title: "retrieval_agent",
            text: "retrieval_agent task: 综合几篇论文",
            status: "completed",
          },
        ]}
        status="completed"
        collapsed={false}
        onToggle={vi.fn()}
      />,
    );

    expect(container.querySelector(".trace-item-retrieval")).not.toBeNull();
  });
});
