from pathlib import Path
import unittest


class SupervisorGraphOrderTest(unittest.TestCase):
    def test_thread_lock_precedes_context_and_memory_reads(self) -> None:
        supervisor_source = Path("src/orchestration/supervisor.py").read_text(encoding="utf-8")

        self.assertIn('builder.add_edge("prepare_turn", "thread_lock")', supervisor_source)
        self.assertIn('builder.add_edge("thread_lock", "build_short_term_context")', supervisor_source)
        self.assertIn('builder.add_edge("build_short_term_context", "recall_memory")', supervisor_source)
        self.assertNotIn('builder.add_edge("recall_memory", "thread_lock")', supervisor_source)

    def test_assessment_does_not_use_static_confidence_rules(self) -> None:
        supervisor_source = Path("src/orchestration/supervisor.py").read_text(encoding="utf-8")

        self.assertNotIn("def _answer_is_confident", supervisor_source)
        self.assertNotIn("_has_strong_retrieval_support", supervisor_source)
        self.assertIn("parse_assessment_decision", supervisor_source)


if __name__ == "__main__":
    unittest.main()
