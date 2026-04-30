"""Small ranking helpers used by evidence retrieval."""

from __future__ import annotations

from domain import ScoredId


def fuse_document_hits(
    *,
    title_hits: list[ScoredId],
    summary_hits: list[ScoredId],
    limit: int,
) -> list[ScoredId]:
    """Fuse title and summary document hits into a single ranked list."""

    return _fuse_weighted_hits(
        groups=[
            (title_hits, 0.7),
            (summary_hits, 1.0),
        ],
        limit=limit,
    )


def fuse_asset_hits(
    *,
    summary_hits: list[ScoredId],
    caption_hits: list[ScoredId] | None = None,
    image_hits: list[ScoredId] | None = None,
    limit: int,
) -> list[ScoredId]:
    """Fuse asset hits from text metadata and optional image-vector recall.

    Default PaperLab behavior uses caption/summary recall and displays images as
    evidence. Image-vector recall can be added by passing ``image_hits``.
    """

    return _fuse_weighted_hits(
        groups=[
            (summary_hits, 1.0),
            (caption_hits or [], 0.9),
            (image_hits or [], 1.1),
        ],
        limit=limit,
    )


def _fuse_weighted_hits(
    *,
    groups: list[tuple[list[ScoredId], float]],
    limit: int,
) -> list[ScoredId]:
    aggregated: dict[str, float] = {}
    for hits, weight in groups:
        for rank, hit in enumerate(hits, start=1):
            rank_bonus = 1.0 / (rank + 1)
            aggregated[hit.entity_id] = aggregated.get(hit.entity_id, 0.0) + (weight * hit.score) + rank_bonus

    fused = [ScoredId(entity_id=entity_id, score=score) for entity_id, score in aggregated.items()]
    fused.sort(key=lambda item: item.score, reverse=True)
    return fused[:limit]
