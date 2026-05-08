from __future__ import annotations

from pathlib import Path

from documents.document_scan import DocumentScanOptions, LocalDocumentScanner
from documents.pdf_parser import PdfParser
import fitz
from fastapi.testclient import TestClient


def test_scan_prunes_ignored_directories_before_visiting_files(tmp_path: Path) -> None:
    visible_pdf = tmp_path / "paper.pdf"
    visible_pdf.write_bytes(b"%PDF-1.4\n")
    ignored_dir = tmp_path / "node_modules"
    ignored_dir.mkdir()
    ignored_pdf = ignored_dir / "ignored.pdf"
    ignored_pdf.write_bytes(b"%PDF-1.4\n")

    scanner = LocalDocumentScanner()
    original_should_include_path = scanner.should_include_path
    visited: list[Path] = []

    def recording_should_include_path(path: Path) -> bool:
        visited.append(path)
        return original_should_include_path(path)

    scanner.should_include_path = recording_should_include_path  # type: ignore[method-assign]

    discovered = scanner.scan_project_documents(tmp_path)

    assert discovered == [visible_pdf.resolve()]
    assert ignored_pdf not in visited


def test_scan_discovers_only_pdf_documents_by_default(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    markdown_path = tmp_path / "notes.md"
    markdown_path.write_text("# Notes\n", encoding="utf-8")

    scanner = LocalDocumentScanner()

    assert scanner.scan_project_documents(tmp_path) == [pdf_path.resolve()]


def test_build_document_record_does_not_call_llm_title_extractor_during_scan(tmp_path: Path) -> None:
    pdf_path = tmp_path / "untitled.pdf"
    document_handle = fitz.open()
    page = document_handle.new_page()
    page.insert_text((72, 72), "A paper title candidate\nAbstract text for extraction.")
    document_handle.save(pdf_path)
    document_handle.close()

    class CountingTitleExtractor:
        calls = 0

        def generate(self, prompt: str) -> str:
            self.calls += 1
            return '{"title": "LLM Title"}'

    title_extractor = CountingTitleExtractor()
    scanner = LocalDocumentScanner(pdf_parser=PdfParser(title_extractor=title_extractor))

    document = scanner.build_document_record("project-a", pdf_path)

    assert document.title == "A paper title candidate"
    assert title_extractor.calls == 0


def test_scan_endpoint_does_not_initialize_heavy_services(tmp_path: Path, monkeypatch) -> None:
    from api.main import app
    from api.routes import documents as documents_route

    pdf_path = tmp_path / "paper.pdf"
    document_handle = fitz.open()
    document_handle.new_page()
    document_handle.save(pdf_path)
    document_handle.close()

    def fail_get_services():
        raise AssertionError("scan should not initialize full API services")

    class EmptyDocumentRepository:
        def get_by_id(self, document_id: str):
            return None

        def get_by_content_hash(self, project_id: str, content_hash: str):
            return None

    monkeypatch.setattr(documents_route, "get_services", fail_get_services)
    monkeypatch.setattr(documents_route, "get_scan_document_repository", lambda: EmptyDocumentRepository())

    response = TestClient(app).post(
        "/documents/scan",
        json={"root_path": str(tmp_path), "project_id": "project-a"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["file_name"] for item in payload["documents"]] == ["paper.pdf"]
    assert payload["documents"][0]["ingested"] is False


def test_metadata_refresh_endpoint_uses_llm_capable_scanner(tmp_path: Path, monkeypatch) -> None:
    from api.main import app
    from api.routes import documents as documents_route

    pdf_path = tmp_path / "paper.pdf"
    document_handle = fitz.open()
    page = document_handle.new_page()
    page.insert_text((72, 72), "Rule title\nAbstract text for extraction.")
    document_handle.save(pdf_path)
    document_handle.close()

    class TitleExtractor:
        def generate(self, prompt: str) -> str:
            return '{"title": "LLM Refined Title"}'

    scanner = LocalDocumentScanner(
        options=DocumentScanOptions(use_llm_metadata=True),
        pdf_parser=PdfParser(title_extractor=TitleExtractor()),
    )

    class EmptyDocumentRepository:
        def get_by_id(self, document_id: str):
            return None

        def get_by_content_hash(self, project_id: str, content_hash: str):
            return None

        def upsert(self, document) -> None:
            pass

    monkeypatch.setattr(documents_route, "get_llm_metadata_scanner", lambda: scanner)
    monkeypatch.setattr(documents_route, "get_scan_document_repository", lambda: EmptyDocumentRepository())

    response = TestClient(app).post(
        "/documents/metadata/refresh",
        json={"root_path": str(tmp_path), "path": str(pdf_path), "project_id": "project-a"},
    )

    assert response.status_code == 200
    assert response.json()["document"]["title"] == "LLM Refined Title"


def test_metadata_refresh_persists_llm_metadata_on_document_row_and_scan_reuses_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from api.main import app
    from api.routes import documents as documents_route
    from domain import Document, DocumentStatus

    refreshed_pdf = tmp_path / "refreshed.pdf"
    plain_pdf = tmp_path / "plain.pdf"
    for pdf_path, title in [(refreshed_pdf, "Rule title"), (plain_pdf, "Plain title")]:
        document_handle = fitz.open()
        page = document_handle.new_page()
        page.insert_text((72, 72), f"{title}\nAbstract text for extraction.")
        document_handle.save(pdf_path)
        document_handle.close()

    class TitleExtractor:
        calls = 0

        def generate(self, prompt: str) -> str:
            self.calls += 1
            return '{"title": "LLM Cached Title"}'

    class InMemoryDocumentRepository:
        def __init__(self) -> None:
            self.rows: dict[str, Document] = {}

        def ensure_tables(self) -> None:
            pass

        def get_by_id(self, document_id: str):
            return self.rows.get(document_id)

        def get_by_content_hash(self, project_id: str, content_hash: str):
            for document in self.rows.values():
                if document.project_id == project_id and document.content_hash == content_hash:
                    return document
            return None

        def upsert(self, document: Document) -> None:
            self.rows[document.id] = document

    document_repository = InMemoryDocumentRepository()
    llm_scanner = LocalDocumentScanner(
        options=DocumentScanOptions(use_llm_metadata=True),
        pdf_parser=PdfParser(title_extractor=TitleExtractor()),
    )
    monkeypatch.setattr(documents_route, "get_llm_metadata_scanner", lambda: llm_scanner)
    monkeypatch.setattr(documents_route, "get_scan_document_repository", lambda: document_repository)

    refresh_response = TestClient(app).post(
        "/documents/metadata/refresh",
        json={"path": str(refreshed_pdf), "project_id": "project-a"},
    )

    assert refresh_response.status_code == 200
    assert refresh_response.json()["document"]["title"] == "LLM Cached Title"
    assert refresh_response.json()["document"]["metadata_source"] == "llm"

    scan_response = TestClient(app).post(
        "/documents/scan",
        json={"root_path": str(tmp_path), "project_id": "project-a"},
    )

    assert scan_response.status_code == 200
    documents_by_name = {item["file_name"]: item for item in scan_response.json()["documents"]}
    assert documents_by_name["refreshed.pdf"]["title"] == "LLM Cached Title"
    assert documents_by_name["refreshed.pdf"]["metadata_source"] == "llm"
    assert documents_by_name["refreshed.pdf"]["metadata_cached"] is True
    assert documents_by_name["refreshed.pdf"]["ingested"] is False
    assert documents_by_name["plain.pdf"]["title"] == "Plain title"
    assert documents_by_name["plain.pdf"]["metadata_source"] == "pdf"
    assert documents_by_name["plain.pdf"]["metadata_cached"] is False

    cached_document = next(iter(document_repository.rows.values()))
    assert cached_document.title == "Rule title"
    assert cached_document.llm_title == "LLM Cached Title"
    assert cached_document.status == DocumentStatus.DISCOVERED
