"""Small ranking helpers used by evidence retrieval.

fusion.py 负责多路召回结果的融合排序。

它接收不同召回通道返回的 ScoredId 列表，例如：
- document.title 召回结果
- document.summary 召回结果
- asset.caption 召回结果
- asset.summary 召回结果
- 可选 asset.image 召回结果

然后按照 entity_id 去重，并使用：
    fused_score += route_weight * hit.score + rank_bonus
进行分数累加。

因此，同一个对象如果被多路同时召回，会获得更高融合分数。
fusion.py 的输出不是最终答案，而是 reranker 精排前的候选列表。

在 RetrieveEvidenceUseCase 中，文档级 fusion 会先筛出候选 document_ids，
后续 chunk 和 asset 检索会被限制在这些候选文档范围内。


"""

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
