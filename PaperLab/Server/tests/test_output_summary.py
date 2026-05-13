from __future__ import annotations

import unittest

from orchestration.output_summary import build_progress_summary
from orchestration.output_summary import parse_structured_assistant_output


class OutputSummaryTest(unittest.TestCase):
    def test_parse_structured_assistant_output_reads_summary_object(self) -> None:
        answer, summary = parse_structured_assistant_output(
            """{
                "answer": "这是最终答复",
                "summary": {
                    "done": "完成了检索和综合",
                    "next": "可以继续追问某篇文献",
                    "pending": "还没有查看用户指定的代码仓库"
                }
            }"""
        )

        self.assertEqual(answer, "这是最终答复")
        self.assertEqual(summary["done"], "完成了检索和综合")
        self.assertEqual(summary["next"], "可以继续追问某篇文献")
        self.assertEqual(summary["pending"], "还没有查看用户指定的代码仓库")

    def test_parse_structured_assistant_output_falls_back_for_plain_text(self) -> None:
        answer, summary = parse_structured_assistant_output("普通文本回复")

        self.assertEqual(answer, "普通文本回复")
        self.assertEqual(summary, build_progress_summary(done="已生成当前回复", next="", pending="尚未提供结构化步骤摘要"))

    def test_parse_structured_assistant_output_extracts_json_from_code_fence(self) -> None:
        answer, summary = parse_structured_assistant_output(
            """```json
            {
              "answer": "这是最终答案。",
              "summary": {
                "done": "已完成回答",
                "next": "可继续深入方法细节",
                "pending": "尚未展开实验分析"
              }
            }
            ```"""
        )

        self.assertEqual(answer, "这是最终答案。")
        self.assertEqual(
            summary,
            build_progress_summary(
                done="已完成回答",
                next="可继续深入方法细节",
                pending="尚未展开实验分析",
            ),
        )


if __name__ == "__main__":
    unittest.main()
