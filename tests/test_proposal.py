"""Keyless tests for PDF proposal extraction (core.proposal.pdf_to_text)."""
import pytest

from autocodabench.core.proposal import pdf_to_text


def _make_text_pdf(text: str) -> bytes:
    """A minimal single-page PDF with extractable text and a correct xref
    table (byte offsets computed here, so it's robust across pypdf versions)."""
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET\n".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_pos))
    return bytes(out)


def test_pdf_round_trip(tmp_path):
    p = tmp_path / "proposal.pdf"
    p.write_bytes(_make_text_pdf("Hello Proposal"))
    assert "Hello Proposal" in pdf_to_text(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_to_text(tmp_path / "nope.pdf")


def test_non_pdf_raises_clear_error(tmp_path):
    p = tmp_path / "notpdf.pdf"
    p.write_text("this is plainly not a pdf")
    with pytest.raises(RuntimeError):
        pdf_to_text(p)


def test_image_only_pdf_raises_clear_error(tmp_path):
    # A page with no text content must raise — never silently return "".
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    p = tmp_path / "blank.pdf"
    with p.open("wb") as fh:
        w.write(fh)
    with pytest.raises(RuntimeError):
        pdf_to_text(p)
