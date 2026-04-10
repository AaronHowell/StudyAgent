"""Document-processing package for StudyAgent."""

from study_agent_documents.chunking import ChunkingOptions, TextChunkBuilder
from study_agent_documents.document_scan import (
    DEFAULT_IGNORED_DIR_NAMES,
    SUPPORTED_DOCUMENT_SUFFIXES,
    DocumentScanOptions,
    LocalDocumentScanner,
)
from study_agent_documents.pdf_parser import PdfParseResult, PdfParser

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
