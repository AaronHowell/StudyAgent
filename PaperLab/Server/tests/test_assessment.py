from __future__ import annotations

import unittest

from orchestration.assessment import parse_assessment_decision
from prompts.builders import build_main_route_messages


class AssessmentDecisionTest(unittest.TestCase):
    def test_parse_confident_assessment(self) -> None:
        decision = parse_assessment_decision('{"answer_confident": true, "next_tasks": []}')

        self.assertTrue(decision.answer_confident)
        self.assertEqual(decision.next_tasks, [])

    def test_parse_insufficient_assessment_keeps_follow_up_tasks(self) -> None:
        decision = parse_assessment_decision(
            """
            {
              "answer_confident": false,
              "next_tasks": [
                "Retrieve chunks about the ablation setup.",
                {"agent": "tool_agent", "task": "Check whether the benchmark has an updated leaderboard."}
              ]
            }
            """
        )

        self.assertFalse(decision.answer_confident)
        self.assertEqual(
            decision.next_tasks,
            [
                "Retrieve chunks about the ablation setup.",
                "tool_agent: Check whether the benchmark has an updated leaderboard.",
            ],
        )

    def test_parse_string_false_as_not_confident(self) -> None:
        decision = parse_assessment_decision('{"answer_confident": "false", "next_tasks": "Retrieve more evidence."}')

        self.assertFalse(decision.answer_confident)
        self.assertEqual(decision.next_tasks, ["Retrieve more evidence."])

    def test_main_route_prompt_includes_assessment_guidance(self) -> None:
        _, user_prompt = build_main_route_messages(
            question="What evidence supports the claim?",
            assessment_guidance=["Retrieve more detail about the experimental setup."],
        )

        self.assertIn("Assessment guidance from previous evidence review:", user_prompt)
        self.assertIn("- Retrieve more detail about the experimental setup.", user_prompt)


if __name__ == "__main__":
    unittest.main()
