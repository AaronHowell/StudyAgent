"""Class-based chunk building for PDF text ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from domain import Chunk, ChunkType, Document, PdfPage


@dataclass(slots=True)
class ChunkingOptions:
    """Chunk sizing options held by one chunk builder instance.

    Attributes:
        max_chars: 单个 chunk 的最大字符数兜底限制。
        overlap_chars: 相邻 chunk 之间保留的重叠字符数兜底限制。
        max_approx_tokens: 单个 chunk 的近似 token 上限，优先于字符限制生效。
        overlap_approx_tokens: 相邻 chunk 的近似 token 重叠预算。
        min_paragraph_chars: 触发短段合并时的最小段落字符阈值。
    """

    max_chars: int = 1800
    overlap_chars: int = 240
    max_approx_tokens: int = 420
    overlap_approx_tokens: int = 64
    min_paragraph_chars: int = 120


class TextChunkBuilder:
    """Build normalized text chunks from parsed PDF pages.

    作用:
        将 PDF 页面文本转换为适合后续嵌入和检索的 `Chunk` 对象列表。
    """

    def __init__(self, options: ChunkingOptions | None = None) -> None:
        self.options = options or ChunkingOptions()

    def split_page_into_paragraphs(self, page_text: str) -> list[str]:
        """Split one normalized page into paragraph-like text segments.

        作用:
            按双换行将页面文本拆成接近自然段的片段。

        Args:
            page_text: 已清洗的页面文本。

        Returns:
            list[str]: 去除空段后的段落文本列表。
        """

        return [part.strip() for part in page_text.split("\n\n") if part.strip()]

    def merge_short_paragraphs(self, paragraphs: list[str]) -> list[str]:
        """Merge overly short paragraphs before chunk assembly.

        作用:
            将过短的段落与后续段落合并，避免过碎的文本直接进入嵌入流程。

        Args:
            paragraphs: 原始段落列表。

        Returns:
            list[str]: 合并后的段落列表。
        """

        if not paragraphs:
            return []

        merged: list[str] = []
        buffer = paragraphs[0]

        for paragraph in paragraphs[1:]:
            if len(buffer) < self.options.min_paragraph_chars:
                buffer = f"{buffer}\n{paragraph}"
            else:
                merged.append(buffer)
                buffer = paragraph

        merged.append(buffer)
        return merged

    def chunk_paragraphs(self, paragraphs: list[str]) -> list[str]:
        """Pack paragraphs into chunk-sized windows with simple overlap.

        作用:
            将段落合并成近似固定大小的文本块，并保留相邻块之间的重叠内容。

        Args:
            paragraphs: 待打包的段落列表。

        Returns:
            list[str]: 构建后的 chunk 文本列表。
        """

        if not paragraphs:
            return []

        chunks: list[str] = []
        current_parts: list[str] = []

        for paragraph in paragraphs:
            paragraph_windows = self._split_oversized_paragraph(paragraph)
            for window in paragraph_windows:
                candidate_parts = current_parts + [window]
                candidate_text = "\n\n".join(candidate_parts).strip()
                if current_parts and self._exceeds_chunk_budget(candidate_text):
                    committed_text = "\n\n".join(current_parts).strip()
                    chunks.append(committed_text)
                    overlap_parts = self._build_overlap_parts(current_parts)
                    current_parts = overlap_parts + [window]
                    if self._exceeds_chunk_budget("\n\n".join(current_parts).strip()):
                        chunks.append(window.strip())
                        current_parts = []
                else:
                    current_parts = candidate_parts

        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())

        return chunks

    def iter_page_chunk_texts(self, pages: Iterable[PdfPage]) -> list[tuple[int, list[str]]]:
        """Turn page texts into per-page chunk text lists.

        作用:
            对每一页执行“分段 -> 合并短段 -> 构造 chunk 文本”的流程。

        Args:
            pages: PDF 页面对象迭代器。

        Returns:
            list[tuple[int, list[str]]]: 每页页码及其 chunk 文本列表的组合结果。
        """

        page_chunks: list[tuple[int, list[str]]] = []
        for page in pages:
            paragraphs = self.split_page_into_paragraphs(page.text)
            merged = self.merge_short_paragraphs(paragraphs)
            chunk_texts = self.chunk_paragraphs(merged)
            page_chunks.append((page.page_number, chunk_texts))
        return page_chunks

    def build_chunks(self, document: Document, pages: list[PdfPage]) -> list[Chunk]:
        """Build normalized `Chunk` objects from extracted PDF pages.

        作用:
            将逐页 chunk 文本进一步封装成系统使用的 `Chunk` 领域对象。

        Args:
            document: 所属文档对象。
            pages: 已解析的 PDF 页面列表。

        Returns:
            list[Chunk]: 可用于后续嵌入和检索的 chunk 对象列表。
        """

        chunks: list[Chunk] = []
        for page_number, chunk_texts in self.iter_page_chunk_texts(pages):
            for chunk_index, chunk_text in enumerate(chunk_texts, start=1):
                chunk_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{document.id}:{page_number}:{chunk_index}:{chunk_text[:80]}",
                    )
                )
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        project_id=document.project_id,
                        document_id=document.id,
                        chunk_index=chunk_index,
                        chunk_type=ChunkType.TEXT,
                        text=chunk_text,
                        page=page_number,
                        section=None,
                        metadata={
                            "source_path": document.path,
                            "page_number": page_number,
                            "chunk_index": chunk_index,
                        },
                    )
                )

        return chunks

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        """Split a single oversized paragraph into smaller windows.

        作用:
            防止某个超长段落单独就超过 embedding 模型可接受的预算。

        Args:
            paragraph: 原始段落文本。

        Returns:
            list[str]: 切分后的段落窗口列表。
        """

        normalized = paragraph.strip()
        if not normalized:
            return []
        if not self._exceeds_chunk_budget(normalized):
            return [normalized]

        pieces: list[str] = []
        words = normalized.split()
        if len(words) <= 1:
            return self._split_dense_text(normalized)

        current_words: list[str] = []
        for word in words:
            candidate = " ".join(current_words + [word]).strip()
            if current_words and self._exceeds_chunk_budget(candidate):
                pieces.append(" ".join(current_words).strip())
                current_words = [word]
            else:
                current_words.append(word)

        if current_words:
            pieces.append(" ".join(current_words).strip())
        return [piece for piece in pieces if piece]

    def _split_dense_text(self, text: str) -> list[str]:
        """Split dense CJK-heavy text with no reliable whitespace separators.

        Args:
            text: 待切分文本。

        Returns:
            list[str]: 近似按 token 预算切好的文本片段。
        """

        parts = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text)
        if not parts:
            return [text]

        pieces: list[str] = []
        current_parts: list[str] = []
        current_budget = 0

        for part in parts:
            token_cost = self._estimate_part_tokens(part)
            if current_parts and current_budget + token_cost > self.options.max_approx_tokens:
                pieces.append(" ".join(current_parts).strip())
                current_parts = [part]
                current_budget = token_cost
            else:
                current_parts.append(part)
                current_budget += token_cost

        if current_parts:
            pieces.append(" ".join(current_parts).strip())
        return [piece for piece in pieces if piece]

    def _build_overlap_parts(self, parts: list[str]) -> list[str]:
        """Build overlap text parts from the tail of the previous chunk.

        Args:
            parts: 上一个 chunk 的段落/窗口列表。

        Returns:
            list[str]: 作为重叠前缀复用的文本片段列表。
        """

        if not parts:
            return []

        overlap_parts: list[str] = []
        current_budget = 0
        current_chars = 0

        for part in reversed(parts):
            part_tokens = self._estimate_text_tokens(part)
            part_chars = len(part)
            if overlap_parts and (
                current_budget + part_tokens > self.options.overlap_approx_tokens
                or current_chars + part_chars > self.options.overlap_chars
            ):
                break
            overlap_parts.insert(0, part)
            current_budget += part_tokens
            current_chars += part_chars

        return overlap_parts

    def _exceeds_chunk_budget(self, text: str) -> bool:
        """Return whether one text exceeds the configured chunk budget.

        Args:
            text: 待检查文本。

        Returns:
            bool: 超过预算时返回 `True`。
        """

        return (
            len(text) > self.options.max_chars
            or self._estimate_text_tokens(text) > self.options.max_approx_tokens
        )

    def _estimate_text_tokens(self, text: str) -> int:
        """Estimate token count conservatively without a model-specific tokenizer.

        Args:
            text: 待估算文本。

        Returns:
            int: 近似 token 数。
        """

        parts = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text)
        return sum(self._estimate_part_tokens(part) for part in parts)

    @staticmethod
    def _estimate_part_tokens(part: str) -> int:
        """Estimate token cost for one text fragment.

        Args:
            part: 单个分词片段。

        Returns:
            int: 近似 token 成本。
        """

        if re.fullmatch(r"[\u4e00-\u9fff]", part):
            return 1
        if re.fullmatch(r"[A-Za-z0-9_]+", part):
            return max(1, math.ceil(len(part) / 4))
        return 1

