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
    title_llm = RecordingTitleLLM(
        """
        {
          "title": "LLM Extracted Paper Title",
          "authors": ["Alice Example", "Bob Example"],
          "summary": "A short summary of metadata extraction for paper retrieval.",
          "keywords": ["metadata", "pdf"],
          "venue": "ACL",
          "year": 2026
        }
        """
    )
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
    assert metadata["author"] == "Alice Example, Bob Example"
    assert metadata["authors"] == ["Alice Example", "Bob Example"]
    assert metadata["summary"] == "A short summary of metadata extraction for paper retrieval."
    assert metadata["keywords"] == ["metadata", "pdf"]
    assert metadata["venue"] == "ACL"
    assert metadata["year"] == 2026
    assert len(title_llm.prompts) == 1
    assert "Actual Paper Title" in title_llm.prompts[0]
    assert "Second page method text" in title_llm.prompts[0]
    assert "Third page text not needed" not in title_llm.prompts[0]


def test_parse_pdf_metadata_keeps_existing_author_over_llm_author(monkeypatch) -> None:
    title_llm = RecordingTitleLLM('{"title": "LLM Title", "authors": ["LLM Author"]}')
    parser = PdfParser(title_extractor=title_llm)
    monkeypatch.setattr(
        parser,
        "_open_reader",
        lambda path: FakeReader(
            metadata={"/Author": "Metadata Author"},
            pages=[FakePage("Actual Paper Title\nLLM Author\nAbstract\n...")],
        ),
    )

    metadata = parser.parse_pdf_metadata(Path("paper.pdf"))

    assert metadata["title"] == "LLM Title"
    assert metadata["author"] == "Metadata Author"
    assert metadata["authors"] == ["LLM Author"]


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


def test_build_asset_metadata_uses_llm_when_caption_context_is_available() -> None:
    title_llm = RecordingTitleLLM(
        """
        {
          "summary": "A result plot comparing metadata extraction accuracy across models.",
          "asset_type": "result_plot",
          "keywords": ["metadata extraction", "accuracy", "models"]
        }
        """
    )
    parser = PdfParser(title_extractor=title_llm)

    metadata = parser._build_asset_metadata(
        caption="Figure 2: Accuracy comparison across extraction models.",
        nearby_text="The proposed LLM metadata extractor improves accuracy over heuristic baselines.",
        page_number=2,
        asset_kind="figure",
    )

    assert metadata == {
        "summary": "A result plot comparing metadata extraction accuracy across models.",
        "asset_type": "result_plot",
        "keywords": ["metadata extraction", "accuracy", "models"],
    }
    assert len(title_llm.prompts) == 1
    assert "Figure 2: Accuracy comparison" in title_llm.prompts[0]


def test_build_asset_metadata_falls_back_to_rules_when_llm_returns_invalid_json() -> None:
    title_llm = RecordingTitleLLM("not json")
    parser = PdfParser(title_extractor=title_llm)

    metadata = parser._build_asset_metadata(
        caption="Figure 3: System architecture overview.",
        nearby_text="The system pipeline contains retrieval and generation modules.",
        page_number=3,
        asset_kind="figure",
    )

    assert metadata["summary"] == "Page 3 image. Caption: Figure 3: System architecture overview."
    assert metadata["asset_type"] == "architecture_diagram"
    assert "architecture" in metadata["keywords"]
