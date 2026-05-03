from __future__ import annotations


def test_document_route_requests_default_to_shared_project_id() -> None:
    from api.schemas import (
        DocumentImagesRequest,
        DocumentIngestionStatusRequest,
        ScanDocumentsRequest,
    )
    from configs import DEFAULT_PROJECT_ID

    assert ScanDocumentsRequest(root_path="C:/papers").project_id == DEFAULT_PROJECT_ID
    assert DocumentImagesRequest(path="C:/papers/a.pdf").project_id == DEFAULT_PROJECT_ID
    assert (
        DocumentIngestionStatusRequest(path="C:/papers/a.pdf").project_id
        == DEFAULT_PROJECT_ID
    )


def test_document_route_requests_accept_explicit_project_id() -> None:
    from api.schemas import (
        DocumentImagesRequest,
        DocumentIngestionStatusRequest,
        ScanDocumentsRequest,
    )

    assert ScanDocumentsRequest(root_path="C:/papers", project_id="custom").project_id == "custom"
    assert DocumentImagesRequest(path="C:/papers/a.pdf", project_id="custom").project_id == "custom"
    assert (
        DocumentIngestionStatusRequest(path="C:/papers/a.pdf", project_id="custom").project_id
        == "custom"
    )
