"""Proposal ingestion: turn a PDF proposal into plain text.

A competition proposal often arrives as a PDF (the bundle-creation
benchmark's instruments ship a ``report.pdf``). The plan phase needs that
content as *text*, and crucially it must be text **at the orchestrator**,
not via a backend-specific file tool: the Claude SDK backend can read a PDF
through its built-in Read tool, but the generic OpenAI-compatible backend's
file tool (:mod:`autocodabench.backends.local_tools`) is UTF-8-only. Doing
the extraction here, once, keeps proposal ingestion **backbone-agnostic** —
every backend receives the same extracted text in the plan prompt.

``pypdf`` is a small pure-Python dependency; it is imported lazily so that
the keyless validator / replay paths never pay for it.
"""
from __future__ import annotations

from pathlib import Path


def pdf_to_text(path: str | Path) -> str:
    """Extract a PDF's text, page by page, joined with blank lines.

    Mirrors the extraction the web UI does inline. Per-page failures are
    tolerated (a single unparseable page should not lose the whole
    document). Raises ``FileNotFoundError`` if the path is missing,
    ``RuntimeError`` if ``pypdf`` is absent or no text could be extracted
    (e.g. a scanned, image-only PDF — which needs OCR, out of scope).
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"proposal PDF not found: {p}")
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "reading a PDF proposal requires 'pypdf' (pip install pypdf)") from e

    try:
        reader = PdfReader(str(p))
    except Exception as e:  # not a PDF, encrypted, truncated, …
        raise RuntimeError(f"could not read {p} as a PDF: {e}") from e
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # one bad page must not sink the document
            pages.append("")
    text = "\n\n".join(s for s in pages if s.strip())
    if not text.strip():
        raise RuntimeError(
            f"no extractable text in {p} (a scanned/image-only PDF needs OCR, "
            "which autocodabench does not perform)")
    return text
