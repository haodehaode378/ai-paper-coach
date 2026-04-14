from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

PDF_BACKEND = "unavailable"

try:
    from pypdf import PdfReader
    PDF_BACKEND = "pypdf"
except Exception:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # type: ignore[assignment]
        PDF_BACKEND = "PyPDF2"
    except Exception:  # pragma: no cover
        PdfReader = None


ARXIV_ABS_RE = re.compile(r"<blockquote class=\"abstract[^>]*>\s*<span[^>]*>Abstract:</span>(.*?)</blockquote>", re.S)
HTML_TAG_RE = re.compile(r"<[^>]+>")
ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/([^?#]+)")




def _clean_title(raw: str) -> str:
    text = HTML_TAG_RE.sub("", str(raw or ""))
    text = text.replace("Title:", "").replace("title:", "")
    text = " ".join(text.split())
    return text.strip()


def infer_title_from_source(source_type: str, source_name: str) -> str:
    source_name = str(source_name or "").strip()
    if not source_name:
        return ""

    if source_type == "upload":
        return _clean_title(Path(source_name).stem.replace("_", " "))

    lower = source_name.lower()
    if "arxiv.org/abs/" in lower:
        try:
            res = requests.get(source_name, timeout=12)
            res.raise_for_status()
            m = ARXIV_TITLE_RE.search(res.text)
            if m:
                title = _clean_title(m.group(1))
                if title:
                    return title
        except Exception:
            pass

    parsed = urlparse(source_name)
    basename = unquote(Path(parsed.path).name).strip()
    if basename:
        if basename.lower().endswith(".pdf"):
            basename = basename[:-4]
        basename = basename.replace("_", " ").replace("-", " ")
        title = _clean_title(basename)
        if title:
            return title

    m = ARXIV_ID_RE.search(lower)
    if m:
        return f"arXiv {m.group(1).strip('/')}"

    return ""

def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        return ""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n\n".join(pages).strip()


def parse_pdf_file(path: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    text = _extract_pdf_text(data)
    status = "success" if text else "failed"
    return {"text": text, "status": status, "source": path, "pdf_backend": PDF_BACKEND}


def _arxiv_abs(url: str) -> str:
    res = requests.get(url, timeout=20)
    res.raise_for_status()
    m = ARXIV_ABS_RE.search(res.text)
    if not m:
        return ""
    cleaned = HTML_TAG_RE.sub("", m.group(1))
    return " ".join(cleaned.split())


def _arxiv_pdf_url(abs_url: str) -> str | None:
    m = ARXIV_ID_RE.search(abs_url.lower())
    if not m:
        return None
    paper_id = m.group(1).strip("/")
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def parse_url(url: str, download_to: str | None = None) -> dict[str, Any]:
    lower = url.lower().strip()
    if lower.endswith(".pdf"):
        res = requests.get(url, timeout=30)
        res.raise_for_status()
        pdf_bytes = res.content
        if download_to:
            Path(download_to).write_bytes(pdf_bytes)
        text = _extract_pdf_text(pdf_bytes)
        return {
            "text": text,
            "status": "success" if text else "failed",
            "source": url,
            "pdf_backend": PDF_BACKEND,
        }

    if "arxiv.org/abs/" in lower:
        pdf_url = _arxiv_pdf_url(url)
        if pdf_url:
            try:
                res = requests.get(pdf_url, timeout=40)
                res.raise_for_status()
                pdf_bytes = res.content
                if download_to:
                    Path(download_to).write_bytes(pdf_bytes)
                text = _extract_pdf_text(pdf_bytes)
                if text:
                    return {"text": text, "status": "success", "source": pdf_url, "pdf_backend": PDF_BACKEND}
            except Exception:
                pass

        abs_text = _arxiv_abs(url)
        if abs_text:
            return {
                "text": f"ABSTRACT\n{abs_text}",
                "status": "summary_only",
                "source": url,
                "pdf_backend": PDF_BACKEND,
            }

    # Generic fallback: minimal text signal.
    return {"text": "", "status": "failed", "source": url, "pdf_backend": PDF_BACKEND}
