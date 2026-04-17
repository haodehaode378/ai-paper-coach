from __future__ import annotations

import html
from io import BytesIO
import re
import unicodedata

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from app.core.orchestrator import to_markdown
from app.core.storage import get_latest_run, get_outputs

router = APIRouter(tags=["export"])


def _load_report(paper_id: str) -> dict:
    run = get_latest_run(paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")

    outputs = get_outputs(run["id"])
    report = outputs.get("final_json") or outputs.get("draft_json")
    if not report:
        raise HTTPException(status_code=404, detail="no report available")
    return report


def _markdown_to_pdf_bytes(markdown_text: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="pdf export dependency missing: install reportlab",
        ) from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        name="BodyCN",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=16,
        spaceAfter=6,
        textColor=colors.HexColor("#111111"),
    )
    heading_styles = {
        1: ParagraphStyle(name="H1CN", parent=body_style, fontSize=18, leading=24, spaceBefore=10, spaceAfter=10),
        2: ParagraphStyle(name="H2CN", parent=body_style, fontSize=14, leading=20, spaceBefore=8, spaceAfter=8),
        3: ParagraphStyle(name="H3CN", parent=body_style, fontSize=12, leading=18, spaceBefore=6, spaceAfter=6),
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="AI Paper Coach Report",
        author="AI Paper Coach",
        leftMargin=46,
        rightMargin=46,
        topMargin=48,
        bottomMargin=48,
    )

    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
    bullet_re = re.compile(r"^[-*]\s+(.*)$")
    ordered_re = re.compile(r"^\d+\.\s+(.*)$")

    story = []
    paragraph_lines: list[str] = []

    def normalize_for_pdf(text: str) -> str:
        if not text:
            return ""
        cleaned = (
            text.replace("\uFFFD", "")
            .replace("\u200B", "")
            .replace("\u200C", "")
            .replace("\u200D", "")
            .replace("\uFE0F", "")
            .replace("\u00A0", " ")
        )
        out: list[str] = []
        for ch in cleaned:
            # STSong-Light 对 emoji / pictograph 支持差，统一剔除避免导出时出现乱码方块。
            if ord(ch) > 0xFFFF and unicodedata.category(ch) == "So":
                continue
            out.append(ch)
        return "".join(out).strip()

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(item.strip() for item in paragraph_lines if item.strip())
        text = normalize_for_pdf(text)
        if text:
            story.append(Paragraph(html.escape(text), body_style))
        paragraph_lines.clear()

    for raw in (markdown_text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            story.append(Spacer(1, 4))
            continue

        heading_match = heading_re.match(line)
        if heading_match:
            flush_paragraph()
            level = min(len(heading_match.group(1)), 3)
            title = normalize_for_pdf(heading_match.group(2).strip())
            if title:
                story.append(Paragraph(html.escape(title), heading_styles[level]))
            continue

        bullet_match = bullet_re.match(line)
        if bullet_match:
            flush_paragraph()
            item = normalize_for_pdf(bullet_match.group(1).strip())
            if item:
                story.append(Paragraph(f"- {html.escape(item)}", body_style))
            continue

        ordered_match = ordered_re.match(line)
        if ordered_match:
            flush_paragraph()
            item = normalize_for_pdf(ordered_match.group(1).strip())
            number = line.split(".", 1)[0].strip()
            if item:
                story.append(Paragraph(f"{html.escape(number)}. {html.escape(item)}", body_style))
            continue

        paragraph_lines.append(line)

    flush_paragraph()
    if not story:
        story.append(Paragraph("No content available.", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


@router.get("/export/{paper_id}.md", response_class=PlainTextResponse)
def export_md(paper_id: str):
    report = _load_report(paper_id)
    return to_markdown(report)


@router.get("/export/{paper_id}.pdf")
def export_pdf(paper_id: str):
    report = _load_report(paper_id)
    markdown = to_markdown(report)
    pdf_bytes = _markdown_to_pdf_bytes(markdown)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="apc-report-{paper_id}.pdf"'
        },
    )
