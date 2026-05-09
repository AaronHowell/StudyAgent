"""Heuristics for deciding which visual assets are worth showing in answers."""

from __future__ import annotations

import re
from collections.abc import Iterable


_HIGH_VALUE_TERMS = (
    "figure",
    "fig",
    "table",
    "workflow",
    "overview",
    "architecture",
    "pipeline",
    "framework",
    "diagram",
    "chart",
    "graph",
    "plot",
    "result",
    "evaluation",
    "comparison",
    "network",
    "matrix",
    "algorithm",
    "ablation",
)

_LOW_VALUE_TERMS = (
    "logo",
    "title and author information",
    "title page",
    "author information",
    "cover image",
)

_HIGH_VALUE_TYPES = (
    "diagram",
    "plot",
    "chart",
    "table",
    "workflow",
    "framework",
    "architecture",
    "network",
    "result",
    "ablation",
)


def filter_informative_asset_hits(asset_hits: Iterable[object], *, question: str = "", limit: int | None = None) -> list[object]:
    """Return only answer-worthy visual assets."""

    kept = [hit for hit in asset_hits if is_informative_asset_hit(hit, question=question)]
    if limit is not None:
        return kept[:limit]
    return kept


def is_informative_asset_hit(hit: object, *, question: str = "") -> bool:
    asset_type = _normalize_text(getattr(hit, "asset_type", ""))
    label = _normalize_text(getattr(hit, "asset_label", ""))
    caption = _normalize_text(getattr(hit, "caption", ""))
    summary = _normalize_text(getattr(hit, "summary", ""))
    file_name = _normalize_text(getattr(hit, "file_name", ""))
    page_number = getattr(hit, "page_number", None)

    merged_text = " ".join(part for part in (asset_type, label, caption, summary, file_name) if part)
    if not merged_text:
        return False
    if any(term in merged_text for term in _LOW_VALUE_TERMS):
        return False

    positive = 0
    if any(term in asset_type for term in _HIGH_VALUE_TYPES):
        positive += 3
    if any(term in label for term in _HIGH_VALUE_TERMS):
        positive += 3
    if any(term in caption for term in _HIGH_VALUE_TERMS):
        positive += 2
    if any(term in summary for term in _HIGH_VALUE_TERMS):
        positive += 2
    if re.search(r"\b(fig(?:ure)?|table)\s*\d+\b", f"{label} {caption}", re.IGNORECASE):
        positive += 2
    if question and _has_question_term_overlap(question, merged_text):
        positive += 1

    weak_raw_name = _is_raw_asset_name(file_name or label)
    weak_summary = not summary or summary in {"no image summary", "没有图片摘要"}
    if page_number == 1 and weak_raw_name and weak_summary and positive < 3:
        return False
    if weak_raw_name and positive < 2:
        return False
    return positive >= 2


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _is_raw_asset_name(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    return bool(
        re.match(r"^page[_-]\d+[_-](image|asset)[_-]\d+", text)
        or re.search(r"\.(png|jpg|jpeg|webp)$", text)
    )


def _has_question_term_overlap(question: str, merged_text: str) -> bool:
    question_terms = {
        token
        for token in re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]+", question.lower())
        if len(token) >= 3
    }
    if not question_terms:
        return False
    asset_terms = set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]+", merged_text.lower()))
    return bool(question_terms & asset_terms)
