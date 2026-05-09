from orchestration import supervisor


def test_structure_retrieval_task_for_cross_paper_synthesis_rewrites_query() -> None:
    query, reason, metadata = supervisor._structure_retrieval_task_for_synthesis(
        question="综合这几篇文章，当前的研究现状是怎么样的？",
        retrieval_query="综合这几篇文章，当前的研究现状是怎么样的？",
        retrieval_reason="Need project-grounded evidence.",
    )

    assert "Cross-paper evidence gathering for final synthesis." in query
    assert "research problem / target task" in query
    assert metadata["retrieval_mode"] == "cross_paper_synthesis"
    assert metadata["evidence_fields"] == [
        "research_problem",
        "method_or_system",
        "main_findings",
        "scope_or_limitations",
    ]
    assert "structured cross-paper evidence" in reason


def test_structure_retrieval_task_for_non_synthesis_question_leaves_query_unchanged() -> None:
    original_query = "已索引论文的标题"
    original_reason = "Need project-grounded evidence."
    query, reason, metadata = supervisor._structure_retrieval_task_for_synthesis(
        question=original_query,
        retrieval_query=original_query,
        retrieval_reason=original_reason,
    )

    assert query == original_query
    assert reason == original_reason
    assert metadata == {}
