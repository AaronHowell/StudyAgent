"""Document-centered domain models.

This module exists so readers can find paper/document data shapes without
opening the full compatibility module.
"""

from domain.models import (
    Document,
    DocumentAsset,
    DocumentDiscoveryResult,
    DocumentProfile,
    DocumentStatus,
    DocumentType,
    PdfPage,
    Project,
    ScanStatus,
    ScanSummary,
)

__all__ = [
    "Document",
    "DocumentAsset",
    "DocumentDiscoveryResult",
    "DocumentProfile",
    "DocumentStatus",
    "DocumentType",
    "PdfPage",
    "Project",
    "ScanStatus",
    "ScanSummary",
]
