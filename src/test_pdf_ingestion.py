import io
import unittest

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdf_ingestion import extract_pdf_pages, extract_pdf_text


def sample_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Pressure 100 psi) Tj ET")
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class TestPdfIngestion(unittest.TestCase):
    def test_extracts_text_and_page_count(self):
        text, pages = extract_pdf_text(sample_pdf())
        self.assertEqual(pages, 1)
        self.assertIn("Pressure 100 psi", text)
        self.assertEqual(len(extract_pdf_pages(sample_pdf())), 1)

    def test_rejects_empty_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf_pages(b"")

    def test_rejects_non_pdf(self):
        with self.assertRaises(ValueError):
            extract_pdf_text(b"not a pdf")


if __name__ == "__main__":
    unittest.main()
