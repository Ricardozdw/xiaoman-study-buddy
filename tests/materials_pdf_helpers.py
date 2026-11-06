"""Small original PDFs for ingestion tests; no third-party course files."""

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, DecodedStreamObject, NameObject


def pdf_bytes(*texts: str | None, password: str | None = None) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            page[NameObject('/Resources')] = DictionaryObject({
                NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref}),
            })
            escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 72 700 Td ({escaped}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
