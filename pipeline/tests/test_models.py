import unittest

from vie_doc_pipeline.models import DocumentAsset


class DocumentAssetTest(unittest.TestCase):
    def test_serialises_with_stable_document_key(self) -> None:
        asset = DocumentAsset(
            publication_id="doi-moi",
            document_id="issue-001",
            source_url="https://example.test/issue-001.pdf",
            object_name="doi-moi/pdf/issue-001.pdf",
        )

        self.assertEqual(asset.key, "doi-moi/document/issue-001")
        self.assertEqual(DocumentAsset.from_dict(asset.to_dict()), asset)
