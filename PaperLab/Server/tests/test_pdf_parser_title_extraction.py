from __future__ import annotations

from pathlib import Path

from documents.pdf_parser import PdfParser


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    def __init__(self, *, metadata: dict[object, object] | None = None, pages: list[FakePage] | None = None) -> None:
        self.metadata = metadata or {}
        self.pages = pages or []


class RecordingTitleLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_parse_pdf_metadata_uses_existing_metadata_title_without_calling_llm(monkeypatch) -> None:
    title_llm = RecordingTitleLLM('{"title": "Wrong Title"}')
    parser = PdfParser(title_extractor=title_llm)
    monkeypatch.setattr(
        parser,
        "_open_reader",
        lambda path: FakeReader(
            metadata={"/Title": "Reliable Metadata Title"},
            pages=[FakePage("First page text")],
        ),
    )

    metadata = parser.parse_pdf_metadata(Path("paper.pdf"))

    assert metadata["title"] == "Reliable Metadata Title"
    assert title_llm.prompts == []


def test_parse_pdf_metadata_uses_llm_title_when_metadata_title_is_missing(monkeypatch) -> None:
    title_llm = RecordingTitleLLM('{"title": "LLM Extracted Paper Title"}')
    parser = PdfParser(title_extractor=title_llm)
    monkeypatch.setattr(
        parser,
        "_open_reader",
        lambda path: FakeReader(
            metadata={},
            pages=[
                FakePage("Conference 2026\nActual Paper Title\nAlice Example\nAbstract\n..."),
                FakePage("Second page method text"),
                FakePage("Third page text not needed"),
            ],
        ),
    )

    metadata = parser.parse_pdf_metadata(Path("paper.pdf"))

    assert metadata["title"] == "LLM Extracted Paper Title"
    assert len(title_llm.prompts) == 1
    assert "Actual Paper Title" in title_llm.prompts[0]
    assert "Second page method text" in title_llm.prompts[0]
    assert "Third page text not needed" not in title_llm.prompts[0]


def test_build_pdf_parser_injects_title_extractor_when_llm_is_configured() -> None:
    from api.dependencies import _build_pdf_parser
    from configs import Settings

    parser = _build_pdf_parser(
        Settings(
            llm_base_url="http://llm.local/v1",
            llm_api_key="test-key",
            llm_model="test-model",
        )
    )

    assert parser.title_extractor is not None


def test_build_pdf_parser_leaves_title_extractor_empty_without_llm_model() -> None:
    from api.dependencies import _build_pdf_parser
    from configs import Settings

    parser = _build_pdf_parser(Settings(llm_model=""))

    assert parser.title_extractor is None
