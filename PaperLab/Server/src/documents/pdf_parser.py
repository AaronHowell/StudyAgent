"""Class-based PDF parsing helpers for the first text-only ingestion path."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import fitz
from PIL import Image, ImageStat
from pypdf import PdfReader
from domain import Document, DocumentAsset, DocumentStatus, DocumentType, PdfPage


@dataclass(slots=True)
class PdfParseResult:
    """Structured parse output for one PDF file.

    作用:
        表示一次 PDF 解析的完整结果，统一承载文档级元数据、逐页文本和图片资源。

    Attributes:
        metadata: PDF 级别元数据，例如标题、作者、页数。
        pages: 逐页提取的文本对象列表。
        images: 提取出的图片资源对象列表。
    """

    metadata: dict[str, object]
    pages: list[PdfPage]
    images: list[DocumentAsset]


@dataclass(slots=True)
class PdfParseConfig:
    """Runtime parsing thresholds and heuristics for one parser instance.

    作用:
        集中管理 PDF 解析中的启发式参数，避免图片过滤、标题抽取和回退渲染逻辑里散落魔法数字。

    Attributes:
        title_line_window: 首页参与标题候选的最大行数。
        title_llm_page_count: 发送给 LLM 抽取标题的首页页数。
        max_title_length: 标题候选允许的最大长度。
        fallback_render_margin: 区域回退渲染时在目标矩形周围增加的边距像素。
        fallback_render_scale: 区域回退渲染的缩放倍率。
        body_image_min_byte_size: 视为正文图片的最小字节阈值。
        body_image_min_width: 视为正文图片的最小宽度。
        body_image_min_height: 视为正文图片的最小高度。
        body_image_min_area: 视为正文图片的最小面积。
        body_image_nearby_text_min_length: 使用附近正文辅助保留图片时要求的最小文本长度。
        body_image_nearby_text_min_area: 有附近正文时的最小图片面积。
        body_image_large_area_threshold: 无编号和图注时，仅凭面积保留图片的阈值。
        fallback_black_mean_threshold: 判定图片接近全黑的灰度均值阈值。
        fallback_white_mean_threshold: 判定图片接近全白的灰度均值阈值。
        fallback_min_stddev: 判定图片灰度变化过小的标准差阈值。
        fallback_max_color_count: 判定图片颜色过少时的最大颜色数量。
    """

    title_line_window: int = 20
    title_llm_page_count: int = 2
    max_title_length: int = 300
    fallback_render_margin: int = 8
    fallback_render_scale: float = 2.0
    caption_render_vertical_margin: int = 10
    caption_render_min_height: float = 160.0
    caption_render_max_height_ratio: float = 0.42
    body_image_min_byte_size: int = 5_000
    body_image_min_width: int = 120
    body_image_min_height: int = 120
    body_image_min_area: int = 40_000
    body_image_nearby_text_min_length: int = 40
    body_image_nearby_text_min_area: int = 120_000
    body_image_large_area_threshold: int = 180_000
    fallback_black_mean_threshold: float = 8.0
    fallback_white_mean_threshold: float = 247.0
    fallback_min_stddev: float = 6.0
    fallback_max_color_count: int = 8


class PdfParser:
    """PDF parser entry object for later metadata extraction and page parsing.

    作用:
        封装 PDF 相关的解析行为，包括元数据提取、逐页文本提取和文本清洗。
    """

    def __init__(
        self,
        extracted_asset_root: Path | None = None,
        config: PdfParseConfig | None = None,
        title_extractor: object | None = None,
    ) -> None:
        """Create one PDF parser instance.

        Args:
            extracted_asset_root: 导出视觉资产时使用的缓存根目录。
            config: 解析配置对象；未提供时使用默认启发式参数。
            title_extractor: 可选 LLM provider，需支持 `generate(prompt) -> str`。
        """

        self.extracted_asset_root = (
            extracted_asset_root
            if extracted_asset_root is not None
            else Path("PaperLabCache/pdf_images")
        )
        self.config = config or PdfParseConfig()
        self.title_extractor = title_extractor

    def parse_pdf_metadata(self, path: Path) -> dict[str, object]:
        """Extract lightweight PDF metadata for later document enrichment.

        作用:
            返回统一形状的 PDF 元数据字典。

        Args:
            path: PDF 文件路径。

        Returns:
            dict[str, object]: 包含来源路径、标题、作者、页数等字段的字典。
        """

        reader = self._open_reader(path)
        metadata = reader.metadata or {}
        llm_metadata: dict[str, object] = {}
        extracted_title = self._extract_title_from_metadata(metadata)

        if not extracted_title:
            llm_metadata = self._extract_metadata_with_llm(reader)
            extracted_title = self._normalize_metadata_value(llm_metadata.get("title"))
            if extracted_title and self._looks_like_bad_title(extracted_title):
                extracted_title = None

        if not extracted_title:
            extracted_title = self._extract_title_from_first_page(reader)

        extracted_author = self._normalize_metadata_value(metadata.get("/Author"))
        if not extracted_author:
            extracted_author = self._build_author_from_llm_metadata(llm_metadata)

        return {
            "source_path": str(path.resolve()),
            **llm_metadata,
            "title": extracted_title or path.stem,
            "author": extracted_author,
            "page_count": len(reader.pages),
        }

    def extract_pdf_pages(self, path: Path) -> list[PdfPage]:
        """Extract page-level text from a PDF file.

        作用:
            逐页提取 PDF 文本，并返回系统内部使用的 `PdfPage` 列表。

        Args:
            path: 待解析的 PDF 文件路径。

        Returns:
            list[PdfPage]: 逐页文本对象列表。
        """

        reader = self._open_reader(path)
        pages: list[PdfPage] = []

        for index, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            normalized_text = self.normalize_page_text(raw_text)
            pages.append(
                PdfPage(
                    page_number=index,
                    text=normalized_text,
                    metadata={
                        "char_count": len(normalized_text),
                        "source_path": str(path.resolve()),
                    },
                )
            )

        return pages

    def extract_pdf_images(
        self,
        document: Document,
        *,
        pages: list[PdfPage] | None = None,
        export_files: bool = True,
    ) -> list[DocumentAsset]:
        """Extract embedded visual assets from a PDF file.

        作用:
            提取 PDF 中可直接访问的视觉资产，并为每个资产生成轻量摘要信息。
            当前实现主要覆盖嵌入图片，但数据模型已经统一到图表视觉资产层。

        Args:
            document: 已建立好的文档对象。
            pages: 可选的逐页文本结果，用于生成图注和摘要。
            export_files: 是否将图片真正导出到本地文件系统。轻量模式下可关闭。

        Returns:
            list[DocumentAsset]: 已导出的视觉资产列表。若 PDF 不含可提取资产则返回空列表。
        """

        path = Path(document.path)
        if pages is None:
            pages = self.extract_pdf_pages(path)

        document_asset_dir = self._build_asset_output_dir(path)

        extracted_images: list[DocumentAsset] = []
        pdf_document = self._open_fitz_document(path)
        try:
            for page_number, page in enumerate(pdf_document, start=1):
                page_text = self._get_page_text(pages, page_number)
                caption_candidates = self._extract_caption_candidates(page_text)
                rendered_caption_labels: set[str] = set()
                page_images = page.get_images(full=True)
                for image_index, image_info in enumerate(page_images, start=1):
                    image_name = self._resolve_image_name(image_info, page_number, image_index)
                    image_bytes = self._resolve_image_bytes(pdf_document, image_info)
                    image_name, image_bytes = self._normalize_image_payload(image_name, image_bytes)
                    extraction_method = "embedded_image"

                    if self._should_render_fallback(image_bytes):
                        fallback_payload = self._render_asset_region(
                            page,
                            image_info,
                            page_number=page_number,
                            image_index=image_index,
                        )
                        if fallback_payload is not None:
                            image_name, image_bytes = fallback_payload
                            extraction_method = "rendered_region"

                    width, height = self._extract_image_dimensions(image_bytes)
                    output_path = document_asset_dir / image_name

                    caption = self._select_caption(caption_candidates, image_index)
                    asset_kind, asset_label, asset_index = self._extract_asset_reference(caption)
                    nearby_text = self._extract_nearby_text(page_text, caption)
                    asset_metadata = self._build_asset_metadata(
                        caption=caption,
                        nearby_text=nearby_text,
                        page_number=page_number,
                        asset_kind=asset_kind,
                    )

                    if not self._should_keep_body_image(
                        width=width,
                        height=height,
                        byte_size=len(image_bytes),
                        caption=caption,
                        asset_label=asset_label,
                        nearby_text=nearby_text,
                    ):
                        continue

                    extracted_images.append(
                        DocumentAsset(
                            id=str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"{document.id}:{page_number}:{image_name}",
                                )
                            ),
                            document_id=document.id,
                            page_number=page_number,
                            file_path="",
                            file_name=output_path.name,
                            asset_kind=asset_kind,
                            asset_label=asset_label,
                            asset_index=asset_index,
                            caption=caption,
                            summary=str(asset_metadata["summary"]),
                            asset_type=str(asset_metadata["asset_type"]),
                            keywords=list(asset_metadata["keywords"]),
                            related_chunk_ids=[],
                            media_type=self._guess_media_type(output_path),
                            byte_size=len(image_bytes),
                            content_bytes=image_bytes,
                            metadata={
                                "source_path": document.path,
                                "project_id": document.project_id,
                                "page_number": page_number,
                                "image_index": image_index,
                                "xref": self._extract_image_xref(image_info),
                                "byte_size": len(image_bytes),
                                "width": width,
                                "height": height,
                                "extraction_method": extraction_method,
                                "exported": False,
                            },
                        )
                    )
                    if asset_label:
                        rendered_caption_labels.add(asset_label)

                caption_assets = self._render_caption_anchored_assets(
                    document=document,
                    page=page,
                    page_number=page_number,
                    caption_candidates=caption_candidates,
                    already_rendered_labels=rendered_caption_labels,
                    export_files=export_files,
                    document_asset_dir=document_asset_dir,
                )
                extracted_images.extend(caption_assets)
        finally:
            pdf_document.close()

        return extracted_images

    def parse_pdf(
        self,
        document: Document,
        *,
        include_images: bool = True,
        export_image_files: bool = True,
    ) -> PdfParseResult:
        """Parse one PDF into metadata, page texts, and image assets.

        作用:
            作为 PDF 解析的统一入口，一次性返回文档级元数据、页文本和图片资源，
            方便后续 API、索引和多模态流程直接消费。

        Args:
            document: 待解析的文档对象。
            include_images: 是否提取图片级资源信息。
            export_image_files: 提取图片时是否导出原图文件。

        Returns:
            PdfParseResult: 结构化的 PDF 解析结果。
        """

        path = Path(document.path)
        pages = self.extract_pdf_pages(path)
        return PdfParseResult(
            metadata=self.parse_pdf_metadata(path),
            pages=pages,
            images=(
                self.extract_pdf_images(
                    document,
                    pages=pages,
                    export_files=export_image_files,
                )
                if include_images
                else []
            ),
        )

    def normalize_page_text(self, text: str) -> str:
        """Normalize raw page text into a cleaner paragraph-friendly form.

        作用:
            对 PDF 原始文本做轻量清洗，减少多余空白和异常换行。

        Args:
            text: 原始页面文本。

        Returns:
            str: 清洗后的文本内容。
        """

        collapsed = re.sub(r"\r\n?", "\n", text)
        collapsed = re.sub(r"[ \t]+", " ", collapsed)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        return collapsed.strip()

    def _extract_title_from_metadata(self, metadata: dict[object, object]) -> str | None:
        """Try to read the PDF title directly from embedded metadata.

        作用:
            尝试从 PDF 元数据中提取标题，并过滤明显不可信的标题值。

        Args:
            metadata: PDF 元数据字典。

        Returns:
            str | None: 合法标题时返回标题字符串，否则返回 `None`。
        """

        candidate = self._normalize_metadata_value(metadata.get("/Title"))
        if not candidate:
            return None
        if self._looks_like_bad_title(candidate):
            return None
        return candidate

    def _extract_metadata_with_llm(self, reader: PdfReader) -> dict[str, object]:
        """Ask an optional LLM extractor to identify paper metadata from early pages.

        作用:
            当 PDF metadata 不完整时，把前几页文本交给可选 LLM 提取器。
            该能力是增强路径，任何异常或低质量返回都会回退到 PDF metadata
            和启发式规则。

        Args:
            reader: 已打开的 PDF 读取器。

        Returns:
            dict[str, object]: LLM 返回并规范化后的 metadata；不可用时返回空字典。
        """

        if self.title_extractor is None:
            return {}
        generate = getattr(self.title_extractor, "generate", None)
        if not callable(generate):
            return {}

        page_texts: list[str] = []
        for page in reader.pages[: self.config.title_llm_page_count]:
            raw_text = page.extract_text() or ""
            normalized_text = self.normalize_page_text(raw_text)
            if normalized_text:
                page_texts.append(normalized_text)

        if not page_texts:
            return {}

        prompt = self._build_metadata_extraction_prompt("\n\n".join(page_texts))
        try:
            response = str(generate(prompt) or "")
        except Exception:
            return {}

        return self._parse_metadata_extraction_response(response)

    def _build_metadata_extraction_prompt(self, first_pages_text: str) -> str:
        """Build the prompt used for optional LLM metadata extraction."""

        return (
            "Extract academic paper metadata from the following PDF text. "
            "Use only the provided text from the first pages. Ignore page headers, footers, "
            "navigation text, and unrelated boilerplate. Return only JSON with this shape: "
            '{"title": "", "authors": [], "summary": "", "keywords": [], "venue": "", '
            '"year": null}. Use empty strings, empty arrays, '
            "Keep summary concise: one or two sentences, not the full abstract. "
            "or null when a field is not present.\n\n"
            f"<pdf_text>\n{first_pages_text[:8000]}\n</pdf_text>"
        )

    def _parse_metadata_extraction_response(self, response: str) -> dict[str, object]:
        """Parse and normalize metadata from one LLM response."""

        cleaned = response.strip()
        if not cleaned:
            return {}

        json_payload = self._extract_json_object(cleaned)
        if not json_payload:
            return {}

        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}

        result: dict[str, object] = {}
        title = self._normalize_metadata_value(parsed.get("title"))
        if title and not self._looks_like_bad_title(title):
            result["title"] = title[: self.config.max_title_length]

        authors = self._normalize_metadata_list(parsed.get("authors"))
        if authors:
            result["authors"] = authors

        summary = self._normalize_metadata_value(parsed.get("summary"))
        if summary:
            result["summary"] = summary

        keywords = self._normalize_metadata_list(parsed.get("keywords"))
        if keywords:
            result["keywords"] = keywords

        for key in ("venue",):
            value = self._normalize_metadata_value(parsed.get(key))
            if value:
                result[key] = value

        year = self._normalize_metadata_year(parsed.get("year"))
        if year is not None:
            result["year"] = year

        return result

    def _build_author_from_llm_metadata(self, metadata: dict[str, object]) -> str | None:
        """Build the legacy author string from LLM authors when PDF metadata is empty."""

        authors = metadata.get("authors")
        if not isinstance(authors, list):
            return None
        normalized_authors = [str(author).strip() for author in authors if str(author).strip()]
        if not normalized_authors:
            return None
        return ", ".join(normalized_authors)

    @staticmethod
    def _normalize_metadata_list(value: object) -> list[str]:
        """Normalize a JSON field into a compact string list."""

        if isinstance(value, list):
            items = value
        elif isinstance(value, str):
            items = re.split(r"\s*[,;]\s*", value)
        else:
            return []

        normalized: list[str] = []
        for item in items:
            text = re.sub(r"\s+", " ", str(item)).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_metadata_year(value: object) -> int | None:
        """Normalize a model-provided year into a plausible integer."""

        if value is None:
            return None
        match = re.search(r"\b(19|20)\d{2}\b", str(value))
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """Return the first likely JSON object from one model response."""

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return text[start : end + 1]

    def _extract_title_from_first_page(self, reader: PdfReader) -> str | None:
        """Fallback title extraction based on the first non-empty page lines.

        作用:
            当元数据标题不可用时，从首页文本中启发式地推断一个候选标题。

        Args:
            reader: 已打开的 PDF 读取器。

        Returns:
            str | None: 推断出的候选标题，若无法找到则返回 `None`。
        """

        if not reader.pages:
            return None

        first_page_text = reader.pages[0].extract_text() or ""
        normalized = self.normalize_page_text(first_page_text)
        if not normalized:
            return None

        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        filtered_lines = [
            line
            for line in lines[: self.config.title_line_window]
            if self._is_title_candidate_line(line)
        ]

        for start_index in range(len(filtered_lines)):
            for size in range(3, 0, -1):
                group = filtered_lines[start_index : start_index + size]
                if not group:
                    continue
                candidate = " ".join(group).strip()
                candidate = re.sub(r"\s+", " ", candidate)
                if not self._looks_like_bad_title(candidate):
                    return candidate[: self.config.max_title_length]

        for line in lines:
            candidate = line.strip()
            if not candidate:
                continue
            if len(candidate) < 5:
                continue
            if self._looks_like_bad_title(candidate):
                continue
            return candidate[: self.config.max_title_length]

        return None

    def _normalize_metadata_value(self, value: object) -> str | None:
        """Normalize one metadata field into a clean optional string.

        作用:
            将原始元数据字段转成干净字符串，统一处理空值和空白字符。

        Args:
            value: 原始元数据字段值。

        Returns:
            str | None: 清洗后的字符串，若无有效内容则返回 `None`。
        """

        if value is None:
            return None

        normalized = str(value).strip()
        return normalized or None

    def _open_reader(self, path: Path) -> PdfReader:
        """Open a PDF reader for a given file path.

        作用:
            封装 PDF 读取器的创建逻辑，便于后续统一替换底层库或增加异常处理。

        Args:
            path: PDF 文件路径。

        Returns:
            PdfReader: 已打开的 PDF 读取器对象。
        """

        return PdfReader(str(path))

    def _open_fitz_document(self, path: Path) -> fitz.Document:
        """Open a PyMuPDF document for image extraction.

        作用:
            使用 PyMuPDF 打开 PDF 文档，专门用于图片资源提取。

        Args:
            path: PDF 文件路径。

        Returns:
            fitz.Document: 已打开的 PyMuPDF 文档对象。
        """

        return fitz.open(path)

    def _looks_like_bad_title(self, candidate: str) -> bool:
        """Return whether one title candidate is obviously low quality.

        作用:
            根据长度、内容模式和常见垃圾值判断一个标题候选是否不可信。

        Args:
            candidate: 待判断的标题候选字符串。

        Returns:
            bool: 若该标题明显不适合作为论文标题则返回 `True`。
        """

        lowered = candidate.strip().lower()
        if not lowered:
            return True
        if len(lowered) < 5:
            return True
        if len(lowered) > self.config.max_title_length:
            return True
        if "@" in lowered:
            return True
        if lowered in {"abstract", "introduction", "contents", "references"}:
            return True
        if lowered.startswith("doi"):
            return True
        if lowered.startswith("arxiv"):
            return True
        if lowered.startswith("www."):
            return True
        if lowered.endswith(".pdf"):
            return True
        if lowered in {"microsoft word", "untitled", "title"}:
            return True
        return False

    def _is_title_candidate_line(self, line: str) -> bool:
        """Return whether one first-page line is worth considering as title text.

        作用:
            过滤首页文本中的明显噪声行，只保留可能构成标题的文本行。

        Args:
            line: 首页中的一行文本。

        Returns:
            bool: 若该行值得作为标题候选则返回 `True`。
        """

        normalized = line.strip()
        lowered = normalized.lower()

        if len(normalized) < 5:
            return False
        if "@" in normalized:
            return False
        if lowered.startswith("abstract"):
            return False
        if lowered.startswith("keywords"):
            return False
        if lowered.startswith("introduction"):
            return False
        if lowered.startswith("authors"):
            return False
        if re.fullmatch(r"\d+", normalized):
            return False
        return True

    def _build_asset_output_dir(self, path: Path) -> Path:
        """Build the output directory used for extracted assets of one PDF.

        作用:
            为单个 PDF 构造稳定的图片资源缓存目录，避免不同文档之间的文件冲突。

        Args:
            path: PDF 文件路径。

        Returns:
            Path: 对应文档的图片缓存目录路径。
        """

        file_hash = sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "document"
        return self.extracted_asset_root / f"{safe_stem}_{file_hash}"

    def _resolve_image_name(self, image: object, page_number: int, image_index: int) -> str:
        """Resolve a deterministic output file name for an extracted PDF image.

        作用:
            为提取出的图片生成稳定、可读、可复用的文件名。

        Args:
            image: 底层 PDF 图片对象或图片信息元组。
            page_number: 图片所在页码。
            image_index: 图片在当前页中的顺序编号。

        Returns:
            str: 生成后的图片文件名。
        """

        raw_name = getattr(image, "name", "") or ""
        suffix = Path(raw_name).suffix.lower()
        if not suffix and isinstance(image, tuple) and len(image) > 0:
            xref = self._extract_image_xref(image)
            if xref is not None:
                suffix = f".{self._guess_extension_from_xref(xref)}"
        suffix = suffix or ".bin"
        if suffix in {".jp2", ".jpx"}:
            suffix = ".jpg"
        return f"page_{page_number:04d}_image_{image_index:03d}{suffix}"

    def _resolve_image_bytes(self, pdf_document: fitz.Document, image: object) -> bytes:
        """Extract raw bytes from one PDF image object.

        作用:
            从 PyMuPDF 的图片对象中取出原始二进制内容，供按需导出和后续处理使用。

        Args:
            pdf_document: 已打开的 PyMuPDF 文档对象。
            image: PyMuPDF 返回的图片信息元组。

        Returns:
            bytes: 图片的原始字节内容。

        Raises:
            ValueError: 当图片对象无法提供原始字节时抛出。
        """

        xref = self._extract_image_xref(image)
        if xref is None:
            raise ValueError("PDF image object does not expose a valid xref.")

        image_payload = pdf_document.extract_image(xref)
        image_bytes = image_payload.get("image")
        if image_bytes is None:
            raise ValueError("PDF image object does not expose raw data.")
        return bytes(image_bytes)

    def _extract_image_xref(self, image: object) -> int | None:
        """Extract the xref identifier from one PyMuPDF image tuple.

        作用:
            从 PyMuPDF 返回的图片信息元组中取出 xref，供进一步提取图片字节。

        Args:
            image: PyMuPDF 返回的图片信息对象。

        Returns:
            int | None: 图片对应的 xref；若无法解析则返回 `None`。
        """

        if isinstance(image, tuple) and image:
            first_item = image[0]
            if isinstance(first_item, int):
                return first_item
        return None

    def _guess_extension_from_xref(self, xref: int) -> str:
        """Return a default extension hint for one xref-based image name.

        作用:
            为没有原始文件名的图片提供一个默认扩展名提示，后续仍会统一转成稳定格式。

        Args:
            xref: 图片 xref 编号。

        Returns:
            str: 估算得到的默认扩展名，不带点号。
        """

        return "png"

    def _normalize_image_payload(self, image_name: str, image_bytes: bytes) -> tuple[str, bytes]:
        """Normalize one extracted image into a browser-friendly payload.

        作用:
            将从 PDF 中拿到的图片重新编码成浏览器更稳定可显示的格式，避免前端画廊出现坏图。

        Args:
            image_name: 当前图片文件名。
            image_bytes: 当前图片原始字节。

        Returns:
            tuple[str, bytes]: 归一化后的文件名和图片字节。
        """

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                converted = image.convert("RGB")
                output_buffer = BytesIO()
                converted.save(output_buffer, format="PNG")
                normalized_name = f"{Path(image_name).stem}.png"
                return normalized_name, output_buffer.getvalue()
        except Exception:
            return image_name, image_bytes

    def _should_render_fallback(self, image_bytes: bytes) -> bool:
        """Return whether one extracted bitmap should fall back to region rendering.

        作用:
            检测直接提取出的位图是否疑似只有蒙版、纯色块或严重失真，
            若质量明显不可信，则触发页面区域截图回退。

        Args:
            image_bytes: 已归一化后的图片字节。

        Returns:
            bool: 若应回退到区域渲染则返回 `True`。
        """

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                grayscale = image.convert("L")
                if grayscale.getbbox() is None:
                    return True

                stat = ImageStat.Stat(grayscale)
                mean_value = stat.mean[0]
                stddev_value = stat.stddev[0]

                # 过亮、过暗或几乎没有灰度变化时，通常是蒙版或坏图。
                if (
                    mean_value <= self.config.fallback_black_mean_threshold
                    or mean_value >= self.config.fallback_white_mean_threshold
                ):
                    return True
                if stddev_value < self.config.fallback_min_stddev:
                    return True

                sampled = grayscale.resize((64, 64))
                sampled_colors = sampled.getcolors(maxcolors=4096)
                if (
                    sampled_colors is not None
                    and len(sampled_colors) <= self.config.fallback_max_color_count
                ):
                    return True
        except Exception:
            return True

        return False

    def _render_asset_region(
        self,
        page: fitz.Page,
        image: object,
        *,
        page_number: int,
        image_index: int,
    ) -> tuple[str, bytes] | None:
        """Render one page region as a fallback visual asset.

        作用:
            当直接提取的位图质量不可信时，根据图片在页面中的位置把该区域重新截图，
            用页面真实渲染结果替代坏图。

        Args:
            page: 当前 PDF 页面对象。
            image: 当前图片信息对象。
            page_number: 当前页码。
            image_index: 当前图片在页面中的顺序编号。

        Returns:
            tuple[str, bytes] | None:
                成功时返回 `(文件名, PNG字节)`，失败时返回 `None`。
        """

        xref = self._extract_image_xref(image)
        if xref is None:
            return None

        try:
            rects = page.get_image_rects(xref)
        except Exception:
            return None

        if not rects:
            return None

        # 同一图片可能出现在多个位置，优先渲染面积最大的那个区域。
        target_rect = max(rects, key=lambda rect: rect.width * rect.height)
        expanded_rect = fitz.Rect(
            max(page.rect.x0, target_rect.x0 - self.config.fallback_render_margin),
            max(page.rect.y0, target_rect.y0 - self.config.fallback_render_margin),
            min(page.rect.x1, target_rect.x1 + self.config.fallback_render_margin),
            min(page.rect.y1, target_rect.y1 + self.config.fallback_render_margin),
        )

        try:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(
                    self.config.fallback_render_scale,
                    self.config.fallback_render_scale,
                ),
                clip=expanded_rect,
                alpha=False,
            )
            rendered_bytes = pixmap.tobytes("png")
        except Exception:
            return None

        render_name = f"page_{page_number:04d}_asset_{image_index:03d}_render.png"
        return render_name, rendered_bytes

    def _guess_media_type(self, output_path: Path) -> str | None:
        """Infer a media type string from the exported image suffix.

        作用:
            根据导出后的图片文件后缀推断媒体类型，方便前端预览和后续处理。

        Args:
            output_path: 图片导出路径。

        Returns:
            str | None: 推断出的媒体类型，若无法识别则返回 `None`。
        """

        suffix = output_path.suffix.lower()
        mapping = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".bin": None,
        }
        return mapping.get(suffix, None)

    def _extract_image_dimensions(self, image_bytes: bytes) -> tuple[int, int]:
        """Read width and height from one extracted image payload.

        作用:
            从图片字节中读取基础尺寸信息，供正文图片过滤和后续展示使用。

        Args:
            image_bytes: 图片原始字节数据。

        Returns:
            tuple[int, int]: 图片宽度和高度；若无法识别则返回 `(0, 0)`。
        """

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                return image.width, image.height
        except Exception:
            return 0, 0

    def _should_keep_body_image(
        self,
        *,
        width: int,
        height: int,
        byte_size: int,
        caption: str,
        asset_label: str,
        nearby_text: str,
    ) -> bool:
        """Return whether one extracted image is likely a body figure.

        作用:
            过滤掉 PDF 中的页眉图标、装饰元素和过小资源，尽量保留正文中的主要图表。

        Args:
            width: 图片宽度。
            height: 图片高度。
            byte_size: 图片字节大小。
            caption: 当前图片匹配到的图注。
            asset_label: 当前资产匹配到的编号标签。
            nearby_text: 图片附近的正文文本。

        Returns:
            bool: 若图片更可能是正文图表则返回 `True`。
        """

        area = width * height
        has_figure_signal = bool(caption or asset_label)

        if has_figure_signal:
            return True
        if byte_size < self.config.body_image_min_byte_size:
            return False
        if width < self.config.body_image_min_width or height < self.config.body_image_min_height:
            return False
        if area < self.config.body_image_min_area:
            return False
        if (
            nearby_text
            and len(nearby_text) >= self.config.body_image_nearby_text_min_length
            and area >= self.config.body_image_nearby_text_min_area
        ):
            return True
        return area >= self.config.body_image_large_area_threshold

    def _get_page_text(self, pages: list[PdfPage], page_number: int) -> str:
        """Return extracted text for one page number if available.

        作用:
            从逐页文本结果中取出指定页码的页面文本。

        Args:
            pages: 已解析的 PDF 页面列表。
            page_number: 目标页码。

        Returns:
            str: 对应页码的页面文本；若不存在则返回空字符串。
        """

        for page in pages:
            if page.page_number == page_number:
                return page.text
        return ""

    def _extract_caption_candidates(self, page_text: str) -> list[str]:
        """Extract figure-like caption candidates from one page text block.

        作用:
            从页面文本中找出像 `Figure 1`、`Fig. 2`、`图 3` 这样的图注候选行。

        Args:
            page_text: 页面完整文本。

        Returns:
            list[str]: 识别出的图注候选列表。
        """

        candidates: list[str] = []
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if not line:
                continue
            if lowered.startswith(
                (
                    "figure ",
                    "figure.",
                    "fig. ",
                    "fig ",
                    "table ",
                    "table.",
                    "tab. ",
                    "tab ",
                    "图 ",
                    "图.",
                    "图表",
                    "表 ",
                    "表.",
                )
            ):
                candidates.append(line)
        return candidates

    def _render_caption_anchored_assets(
        self,
        *,
        document: Document,
        page: fitz.Page,
        page_number: int,
        caption_candidates: list[str],
        already_rendered_labels: set[str],
        export_files: bool,
        document_asset_dir: Path,
    ) -> list[DocumentAsset]:
        """Render assets anchored by Figure/Table captions.

        作用:
            对 LaTeX/TikZ/矢量图等没有 embedded image 的情况，优先根据 caption
            在页面中推断一个视觉区域并渲染截图。

        Args:
            document: 当前文档对象。
            page: 当前 PDF 页面对象。
            page_number: 页码。
            caption_candidates: 当前页识别出的 caption 候选。
            already_rendered_labels: 当前页已由 embedded image 命中的标签集合。
            export_files: 是否导出图片文件。
            document_asset_dir: 导出目录。

        Returns:
            list[DocumentAsset]: 基于 caption 渲染得到的视觉资产列表。
        """

        if not caption_candidates:
            return []

        page_blocks = self._get_page_blocks(page)
        assets: list[DocumentAsset] = []
        rendered_labels = set(already_rendered_labels)

        for caption_index, caption in enumerate(caption_candidates, start=1):
            asset_kind, asset_label, asset_index = self._extract_asset_reference(caption)
            dedupe_key = asset_label or caption
            if dedupe_key in rendered_labels:
                continue

            caption_rect = self._find_caption_rect(page_blocks, caption)
            if caption_rect is None:
                continue

            asset_rect = self._build_caption_anchor_rect(page, caption_rect, asset_kind)
            if asset_rect is None:
                continue

            rendered_payload = self._render_rect_to_png(
                page,
                asset_rect,
                page_number=page_number,
                asset_index=caption_index,
                suffix="caption",
            )
            if rendered_payload is None:
                continue

            image_name, image_bytes = rendered_payload
            width, height = self._extract_image_dimensions(image_bytes)
            nearby_text = self._extract_nearby_text(self._normalize_block_text(page_blocks), caption)
            asset_metadata = self._build_asset_metadata(
                caption=caption,
                nearby_text=nearby_text,
                page_number=page_number,
                asset_kind=asset_kind,
            )
            output_path = document_asset_dir / image_name

            assets.append(
                DocumentAsset(
                    id=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{document.id}:{page_number}:caption:{dedupe_key}",
                        )
                    ),
                    document_id=document.id,
                    page_number=page_number,
                    file_path="",
                    file_name=output_path.name,
                    asset_kind=asset_kind,
                    asset_label=asset_label,
                    asset_index=asset_index,
                    caption=caption,
                    summary=str(asset_metadata["summary"]),
                    asset_type=str(asset_metadata["asset_type"]),
                    keywords=list(asset_metadata["keywords"]),
                    related_chunk_ids=[],
                    media_type=self._guess_media_type(output_path),
                    byte_size=len(image_bytes),
                    content_bytes=image_bytes,
                    metadata={
                        "source_path": document.path,
                        "project_id": document.project_id,
                        "page_number": page_number,
                        "caption_index": caption_index,
                        "caption_bbox": [caption_rect.x0, caption_rect.y0, caption_rect.x1, caption_rect.y1],
                        "render_bbox": [asset_rect.x0, asset_rect.y0, asset_rect.x1, asset_rect.y1],
                        "width": width,
                        "height": height,
                        "extraction_method": "caption_anchored_region",
                        "exported": False,
                    },
                )
            )
            rendered_labels.add(dedupe_key)

        return assets

    def _get_page_blocks(self, page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
        """Return normalized text blocks for one page.

        Args:
            page: 当前页面对象。

        Returns:
            list[tuple[float, float, float, float, str]]: 页面文本块列表。
        """

        blocks: list[tuple[float, float, float, float, str]] = []
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[:5]
            normalized_text = self.normalize_page_text(str(text))
            if not normalized_text:
                continue
            blocks.append((float(x0), float(y0), float(x1), float(y1), normalized_text))
        return blocks

    def _find_caption_rect(
        self,
        page_blocks: list[tuple[float, float, float, float, str]],
        caption: str,
    ) -> fitz.Rect | None:
        """Find the page rectangle for one caption text.

        Args:
            page_blocks: 页面文本块列表。
            caption: 目标 caption。

        Returns:
            fitz.Rect | None: 命中的文本块矩形。
        """

        normalized_caption = self.normalize_page_text(caption).lower()
        for x0, y0, x1, y1, text in page_blocks:
            normalized_text = self.normalize_page_text(text).lower()
            if normalized_caption in normalized_text or normalized_text in normalized_caption:
                return fitz.Rect(x0, y0, x1, y1)
        return None

    def _build_caption_anchor_rect(
        self,
        page: fitz.Page,
        caption_rect: fitz.Rect,
        asset_kind: str,
    ) -> fitz.Rect | None:
        """Build one render region around a caption anchor.

        作用:
            对标准论文采用保守规则：
            - Figure 通常在 caption 上方
            - Table 通常在 caption 下方
            - 使用列宽近似，而不是整页宽度

        Args:
            page: 当前 PDF 页面对象。
            caption_rect: caption 的文本矩形。
            asset_kind: 资产类别。

        Returns:
            fitz.Rect | None: 渲染区域；若区域非法则返回 `None`。
        """

        page_rect = page.rect
        page_mid_x = (page_rect.x0 + page_rect.x1) / 2
        is_left_column = caption_rect.x0 < page_mid_x
        if page_rect.width >= 500:
            column_left = page_rect.x0 if is_left_column else page_mid_x
            column_right = page_mid_x if is_left_column else page_rect.x1
        else:
            column_left = page_rect.x0
            column_right = page_rect.x1

        vertical_margin = self.config.caption_render_vertical_margin
        max_height = max(
            self.config.caption_render_min_height,
            page_rect.height * self.config.caption_render_max_height_ratio,
        )

        if asset_kind == "table":
            y0 = caption_rect.y1 + vertical_margin
            y1 = min(page_rect.y1, y0 + max_height)
        else:
            y1 = caption_rect.y0 - vertical_margin
            y0 = max(page_rect.y0, y1 - max_height)

        if y1 <= y0:
            return None

        render_rect = fitz.Rect(column_left, y0, column_right, y1)
        if render_rect.width <= 8 or render_rect.height <= 8:
            return None
        return render_rect

    def _render_rect_to_png(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        *,
        page_number: int,
        asset_index: int,
        suffix: str,
    ) -> tuple[str, bytes] | None:
        """Render one page rectangle to PNG bytes.

        Args:
            page: 当前页面对象。
            rect: 目标渲染区域。
            page_number: 页码。
            asset_index: 页内顺序号。
            suffix: 文件名后缀。

        Returns:
            tuple[str, bytes] | None: 成功时返回文件名和 PNG 数据。
        """

        try:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(
                    self.config.fallback_render_scale,
                    self.config.fallback_render_scale,
                ),
                clip=rect,
                alpha=False,
            )
            rendered_bytes = pixmap.tobytes("png")
        except Exception:
            return None

        render_name = f"page_{page_number:04d}_asset_{asset_index:03d}_{suffix}.png"
        return render_name, rendered_bytes

    @staticmethod
    def _normalize_block_text(
        page_blocks: list[tuple[float, float, float, float, str]],
    ) -> str:
        """Merge page blocks into one normalized helper string.

        Args:
            page_blocks: 页面文本块列表。

        Returns:
            str: 合并后的页面文本。
        """

        return "\n".join(text for _, _, _, _, text in page_blocks)

    def _select_caption(self, caption_candidates: list[str], image_index: int) -> str:
        """Select one caption candidate for the current image index.

        作用:
            在当前页存在多张图或多个图注候选时，为当前图片挑选一个图注。

        Args:
            caption_candidates: 当前页中的图注候选列表。
            image_index: 当前图片在页面中的顺序编号，从 1 开始。

        Returns:
            str: 选中的图注文本；若无图注候选则返回空字符串。
        """

        if not caption_candidates:
            return ""
        return caption_candidates[min(image_index - 1, len(caption_candidates) - 1)]

    def _extract_asset_reference(self, caption: str) -> tuple[str, str, int | None]:
        """Extract a normalized asset kind, label, and index from a caption.

        Args:
            caption: Raw caption text for one image.

        Returns:
            tuple[str, str, int | None]:
                - Asset kind such as `figure` or `table`
                - Normalized asset label such as `Figure 3` or `Table 1`
                - Numeric asset index if it can be parsed, otherwise `None`
        """

        if not caption:
            return "visual", "", None

        patterns = [
            r"\b(Figure|Fig\.?)\s*(\d+)\b",
            r"\b(Table|Tab\.?)\s*(\d+)\b",
            r"\b(图)\s*(\d+)\b",
            r"\b(表)\s*(\d+)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, caption, flags=re.IGNORECASE)
            if not match:
                continue

            label_prefix = match.group(1).lower()
            asset_index = int(match.group(2))

            if label_prefix.startswith("fig"):
                return "figure", f"Figure {asset_index}", asset_index
            if label_prefix.startswith("tab"):
                return "table", f"Table {asset_index}", asset_index
            if label_prefix == "图":
                return "figure", f"图 {asset_index}", asset_index
            if label_prefix == "表":
                return "table", f"表 {asset_index}", asset_index

        return "visual", "", None

    def _extract_nearby_text(self, page_text: str, caption: str) -> str:
        """Build a short nearby-text snippet for image summarization.

        作用:
            从图注附近或页面开头截取一小段正文，作为图片轻量摘要的补充上下文。

        Args:
            page_text: 页面完整文本。
            caption: 当前图片的图注文本。

        Returns:
            str: 清洗后的附近文本片段。
        """

        if not page_text:
            return ""

        if caption and caption in page_text:
            start = page_text.find(caption)
            left = max(0, start - 220)
            right = min(len(page_text), start + len(caption) + 220)
            snippet = page_text[left:right]
        else:
            snippet = page_text[:400]

        return re.sub(r"\s+", " ", snippet).strip()

    def _build_image_summary(self, caption: str, nearby_text: str, page_number: int) -> str:
        """Build a lightweight text summary for one extracted image.

        作用:
            为图片生成一段可检索、可展示的轻量摘要文本，让 Agent 先理解“图大概讲什么”。

        Args:
            caption: 图片图注。
            nearby_text: 图片附近的正文文本。
            page_number: 图片所在页码。

        Returns:
            str: 生成后的图片摘要文本。
        """

        if caption:
            return f"Page {page_number} image. Caption: {caption}"
        if nearby_text:
            return f"Page {page_number} image. Nearby text: {nearby_text[:240]}"
        return f"Page {page_number} image with no extracted caption."

    def _build_asset_metadata(
        self,
        *,
        caption: str,
        nearby_text: str,
        page_number: int,
        asset_kind: str,
    ) -> dict[str, object]:
        """Build summary, type, and keywords for one visual asset.

        作用:
            优先用可选 LLM 根据图注和附近正文生成更好的视觉资产 metadata。
            当 LLM 不可用、输入上下文不足或输出不可解析时，回退到原规则。
        """

        llm_metadata = self._extract_asset_metadata_with_llm(
            caption=caption,
            nearby_text=nearby_text,
            page_number=page_number,
            asset_kind=asset_kind,
        )
        if llm_metadata:
            return llm_metadata
        return self._build_rule_based_asset_metadata(
            caption=caption,
            nearby_text=nearby_text,
            page_number=page_number,
            asset_kind=asset_kind,
        )

    def _build_rule_based_asset_metadata(
        self,
        *,
        caption: str,
        nearby_text: str,
        page_number: int,
        asset_kind: str,
    ) -> dict[str, object]:
        """Build asset metadata with deterministic fallback rules."""

        return {
            "summary": self._build_image_summary(caption, nearby_text, page_number),
            "asset_type": self._infer_asset_type(caption, nearby_text, asset_kind),
            "keywords": self._extract_keywords(caption, nearby_text),
        }

    def _extract_asset_metadata_with_llm(
        self,
        *,
        caption: str,
        nearby_text: str,
        page_number: int,
        asset_kind: str,
    ) -> dict[str, object]:
        """Ask the optional LLM to summarize and classify one asset from text context."""

        context = f"{caption}\n{nearby_text}".strip()
        if not context:
            return {}
        if self.title_extractor is None:
            return {}
        generate = getattr(self.title_extractor, "generate", None)
        if not callable(generate):
            return {}

        prompt = self._build_asset_metadata_prompt(
            caption=caption,
            nearby_text=nearby_text,
            page_number=page_number,
            asset_kind=asset_kind,
        )
        try:
            response = str(generate(prompt) or "")
        except Exception:
            return {}
        return self._parse_asset_metadata_response(response)

    def _build_asset_metadata_prompt(
        self,
        *,
        caption: str,
        nearby_text: str,
        page_number: int,
        asset_kind: str,
    ) -> str:
        """Build the prompt for text-only visual asset metadata extraction."""

        allowed_types = (
            "result_plot, architecture_diagram, workflow_diagram, table, "
            "dataset_table, equation, ablation_plot, qualitative_example, unknown"
        )
        return (
            "Build metadata for one academic paper visual asset using only the provided "
            "caption and nearby text. Do not invent visual details that are not present. "
            "Return only JSON with this shape: "
            '{"summary": "", "asset_type": "unknown", "keywords": []}. '
            f"asset_type must be one of: {allowed_types}.\n\n"
            f"Page: {page_number}\n"
            f"Asset kind: {asset_kind or 'visual'}\n"
            f"Caption: {caption or '- none'}\n"
            f"Nearby text: {nearby_text[:1200] or '- none'}"
        )

    def _parse_asset_metadata_response(self, response: str) -> dict[str, object]:
        """Parse and validate one LLM asset metadata response."""

        json_payload = self._extract_json_object(response.strip())
        if not json_payload:
            return {}
        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}

        summary = self._normalize_metadata_value(parsed.get("summary"))
        if not summary:
            return {}

        asset_type = self._normalize_asset_type(parsed.get("asset_type"))
        keywords = self._normalize_metadata_list(parsed.get("keywords"))
        return {
            "summary": summary,
            "asset_type": asset_type,
            "keywords": keywords,
        }

    @staticmethod
    def _normalize_asset_type(value: object) -> str:
        """Normalize model output into one supported asset type label."""

        normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
        allowed_types = {
            "result_plot",
            "architecture_diagram",
            "workflow_diagram",
            "table",
            "dataset_table",
            "equation",
            "ablation_plot",
            "qualitative_example",
            "unknown",
        }
        return normalized if normalized in allowed_types else "unknown"

    def _infer_asset_type(self, caption: str, nearby_text: str, asset_kind: str) -> str:
        """Infer a coarse visual asset type from caption and nearby text.

        作用:
            根据图注和附近文本给视觉资产打一个粗粒度类型标签，便于后续筛选和检索。

        Args:
            caption: 图片图注。
            nearby_text: 图片附近的正文文本。
            asset_kind: 视觉资产类别。

        Returns:
            str: 推断出的视觉资产类型标签。
        """

        if asset_kind == "table":
            return "table"

        text = f"{caption} {nearby_text}".lower()
        if any(token in text for token in {"architecture", "framework", "system", "pipeline"}):
            return "architecture_diagram"
        if any(token in text for token in {"result", "accuracy", "f1", "auc", "performance"}):
            return "result_plot"
        if any(token in text for token in {"workflow", "procedure", "process", "overview"}):
            return "workflow_diagram"
        if any(token in text for token in {"table", "dataset", "benchmark"}):
            return "table_or_benchmark"
        return "unknown"

    def _extract_keywords(self, caption: str, nearby_text: str) -> list[str]:
        """Extract a few lightweight keywords from image description text.

        作用:
            从图注和附近文本中抽取少量关键词，作为图片的轻量语义标签。

        Args:
            caption: 图片图注。
            nearby_text: 图片附近的正文文本。

        Returns:
            list[str]: 去重后的关键词列表。
        """

        text = f"{caption} {nearby_text}".lower()
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text)
        stop_words = {
            "figure",
            "page",
            "image",
            "with",
            "from",
            "that",
            "this",
            "using",
            "show",
            "shows",
            "results",
        }
        keywords: list[str] = []
        for word in words:
            if word in stop_words:
                continue
            if word not in keywords:
                keywords.append(word)
            if len(keywords) >= 8:
                break
        return keywords


if __name__ == "__main__":
    import json
    import sys

    # 直接运行文件时，优先修改这里的测试参数。
    TEST_PDF_PATH = Path(r"C:\Users\Aaron_Howell\Desktop\postgraduate\PaperStore\2025.acl-long.562.pdf")
    TEST_INCLUDE_IMAGES = True
    TEST_EXPORT_IMAGE_FILES = True

    pdf_path = TEST_PDF_PATH.expanduser().resolve()
    document = Document(
        id="debug-document",
        project_id="debug-project",
        path=str(pdf_path),
        file_name=pdf_path.name,
        doc_type=DocumentType.PDF,
        title=pdf_path.stem,
        status=DocumentStatus.DISCOVERED,
        content_hash="debug",
    )

    pdf_parser = PdfParser()
    parse_result = pdf_parser.parse_pdf(
        document,
        include_images=TEST_INCLUDE_IMAGES,
        export_image_files=TEST_EXPORT_IMAGE_FILES,
    )

    preview_payload = {
        "metadata": parse_result.metadata,
        "page_count": len(parse_result.pages),
        "image_count": len(parse_result.images),
        "first_page_preview": (
            parse_result.pages[0].text[:300] if parse_result.pages else ""
        ),
        "images": [
            {
                "page_number": image.page_number,
                "file_name": image.file_name,
                "file_path": image.file_path,
                "figure_label": image.figure_label,
                "figure_index": image.figure_index,
                "caption": image.caption,
                "summary": image.summary,
                "asset_type": image.asset_type,
                "keywords": image.keywords,
                "extraction_method": image.metadata.get("extraction_method", ""),
            }
            for image in parse_result.images[:5]
        ],
    }

    sys.stdout.buffer.write(json.dumps(preview_payload, ensure_ascii=False, indent=2).encode("utf-8"))



"""
parse_pdf(document)
  ↓
extract_pdf_pages(path)
  - pypdf 打开 PDF
  - page.extract_text()
  - normalize_page_text()
  - 得到 PdfPage[]

  ↓
parse_pdf_metadata(path)
  - pypdf 读取 metadata
  - 从 /Title 提取标题
  - 如果标题不可信：
      调用 _extract_metadata_with_llm(reader)
      - 取前 2 页文本
      - 构造 metadata 提取 prompt
      - title_extractor.generate(prompt)
      - 解析 JSON title/authors/summary/keywords/venue/year
      - 过滤坏标题
  - 如果 LLM 不可用或失败：
      _extract_title_from_first_page(reader)
  - author 优先使用 /Author，缺失时使用 LLM authors 拼接
  - 返回 source_path / title / author / page_count，以及可用的 LLM metadata 字段

  ↓
extract_pdf_images(document, pages)
  - PyMuPDF 打开 PDF
  - page.get_images(full=True)
  - extract_image(xref)
  - Pillow 转 PNG
  - 坏图 fallback 到页面区域截图
  - caption 规则匹配
  - 生成 summary / asset_type / keywords
  - 过滤小图
  - 生成 DocumentAsset
  - caption-anchored rendering 补充矢量图/表格

  ↓
返回 PdfParseResult(metadata, pages, images)
"""
