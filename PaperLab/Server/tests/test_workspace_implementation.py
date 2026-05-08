from __future__ import annotations

import unittest

from contracts import AgentTask
from workers.workspace.implementation import (
    WorkspaceImplementationState,
    build_implementation_report,
    build_initial_implementation_state,
    record_workspace_observation,
)


WORKSPACE_AGENT_SOURCE = "src/workers/workspace/agent.py"


class WorkspaceImplementationStateTest(unittest.TestCase):
    def test_build_initial_state_from_structured_task(self) -> None:
        task = AgentTask(
            task_id="task-1",
            task_type="implementation",
            agent_name="workspace_agent",
            query="Add graph state comments",
            reason="Need local implementation work.",
            constraints={
                "objective": "Document each graph state field.",
                "plan": ["Inspect graph_state.py", "Add field comments"],
                "acceptance_criteria": ["Every field has a clear comment"],
                "constraints": ["Keep behavior unchanged"],
                "max_steps": 4,
            },
            metadata={},
        )

        state = build_initial_implementation_state(task)

        self.assertEqual(state.objective, "Document each graph state field.")
        self.assertEqual(state.plan, ["Inspect graph_state.py", "Add field comments"])
        self.assertEqual(state.acceptance_criteria, ["Every field has a clear comment"])
        self.assertEqual(state.constraints, ["Keep behavior unchanged"])
        self.assertEqual(state.max_steps, 4)
        self.assertEqual(state.current_step, "Inspect graph_state.py")

    def test_record_observation_updates_progress_lists(self) -> None:
        state = WorkspaceImplementationState(
            task_id="task-1",
            objective="Implement feature",
            plan=["Edit file", "Run tests"],
            acceptance_criteria=["Tests pass"],
            constraints=[],
            max_steps=3,
        )

        updated = record_workspace_observation(
            state,
            action="write",
            summary="Updated graph_state.py",
            content="ok",
            changed_files=["PaperLab/Server/src/orchestration/graph_state.py"],
            test_result=None,
            blocker=None,
            next_actions=["Run focused tests"],
        )

        self.assertEqual(updated.completed_steps, ["Edit file"])
        self.assertEqual(updated.current_step, "Run tests")
        self.assertEqual(updated.changed_files, ["PaperLab/Server/src/orchestration/graph_state.py"])
        self.assertEqual(updated.next_actions, ["Run focused tests"])
        self.assertEqual(updated.action_history[0]["action"], "write")

    def test_build_report_contains_implementation_metadata(self) -> None:
        state = WorkspaceImplementationState(
            task_id="task-1",
            objective="Implement feature",
            plan=["Edit file"],
            acceptance_criteria=["Tests pass"],
            constraints=[],
            max_steps=2,
            completed_steps=["Edit file"],
            changed_files=["src/example.py"],
            test_results=["unit tests passed"],
            next_actions=[],
        )

        result = build_implementation_report(state, agent_name="workspace_agent", status="completed")

        self.assertEqual(result.status, "completed")
        self.assertIn("Implementation report", result.summary)
        self.assertEqual(result.metadata["implementation_report"]["changed_files"], ["src/example.py"])
        self.assertEqual(result.metadata["workspace_sources"][0]["path"], "src/example.py")

    def test_workspace_agent_graph_source_is_not_on_main_path(self) -> None:
        from pathlib import Path

        supervisor_source = Path("src/orchestration/supervisor.py").read_text(encoding="utf-8")

        self.assertFalse(Path(WORKSPACE_AGENT_SOURCE).exists())
        self.assertNotIn("build_workspace_agent_graph", supervisor_source)
        self.assertNotIn("workspace_agent_graph", supervisor_source)

    def test_supervisor_does_not_dispatch_workspace_specialist_task(self) -> None:
        from pathlib import Path

        source = Path("src/orchestration/supervisor.py").read_text(encoding="utf-8")

        self.assertNotIn('agent_name="workspace_agent"', source)
        self.assertNotIn('task_type="implementation"', source)
        self.assertNotIn("workspace_query", source)

    def test_workspace_prompt_describes_implementation_specialist_actions(self) -> None:
        from prompts.builders import build_workspace_agent_selection_messages

        system_prompt, user_prompt = build_workspace_agent_selection_messages(
            task_query="objective: implement feature",
            reason="Need local changes.",
        )

        self.assertIn("goal-driven implementation specialist", system_prompt)
        self.assertIn("list/read/search", system_prompt)
        self.assertIn("write/run", system_prompt)
        self.assertIn("finish", system_prompt)
        self.assertIn("implementation state", user_prompt)


if __name__ == "__main__":
    unittest.main()
