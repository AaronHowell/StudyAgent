"""本包负责论文、PDF 与本地文档的扫描、解析和切分。"""

from documents.chunking import ChunkingOptions, TextChunkBuilder
from documents.document_scan import (
    DEFAULT_IGNORED_DIR_NAMES,
    SUPPORTED_DOCUMENT_SUFFIXES,
    DocumentScanOptions,
    LocalDocumentScanner,
)
from documents.pdf_parser import PdfParseResult, PdfParser

__all__ = [
    "ChunkingOptions",
    "DEFAULT_IGNORED_DIR_NAMES",
    "DocumentScanOptions",
    "LocalDocumentScanner",
    "PdfParseResult",
    "PdfParser",
    "SUPPORTED_DOCUMENT_SUFFIXES",
    "TextChunkBuilder",
]

