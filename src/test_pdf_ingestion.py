import unittest

from pdf_ingestion import extract_pdf_pages, extract_pdf_text


class TestPdfIngestion(unittest.TestCase):
    def test_rejects_empty_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf_pages(b"")

    def test_rejects_non_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf_text(b"not a pdf")


if __name__ == "__main__":
    unittest.main()
