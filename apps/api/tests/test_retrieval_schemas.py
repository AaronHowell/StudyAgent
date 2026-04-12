import unittest

from study_agent_api.schemas import RetrievalEvidenceResponse


class RetrievalResponseSchemaTest(unittest.TestCase):
    def test_accepts_documents_chunks_assets_and_citations(self) -> None:
        response = RetrievalEvidenceResponse.model_validate(
            {
                "query": "retrieval",
                "documents": [
                    {
                        "document_id": "doc-1",
                        "score": 0.91,
                        "title": "Paper A",
                        "file_name": "a.pdf",
                        "path": "C:/docs/a.pdf",
                        "status": "indexed",
                    }
                ],
                "text_chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "score": 0.77,
                        "chunk_index": 0,
                        "page": 4,
                        "section": "Method",
                        "text": "retrieval chunk",
                    }
                ],
                "assets": [
                    {
                        "asset_id": "asset-1",
                        "document_id": "doc-1",
                        "score": 0.66,
                        "page_number": 5,
                        "asset_label": "Figure 2",
                        "caption": "Figure 2: Pipeline",
                        "summary": "Pipeline figure",
                        "asset_type": "workflow_diagram",
                        "file_name": "figure2.png",
                        "file_path": "C:/cache/figure2.png",
                    }
                ],
                "citations": [
                    {
                        "document_id": "doc-1",
                        "document_title": "Paper A",
                        "chunk_id": "chunk-1",
                        "page": 4,
                        "locator": "p.4",
                    }
                ],
            }
        )

        self.assertEqual(response.documents[0].document_id, "doc-1")
        self.assertEqual(response.text_chunks[0].chunk_id, "chunk-1")
        self.assertEqual(response.assets[0].asset_id, "asset-1")


if __name__ == "__main__":
    unittest.main()
