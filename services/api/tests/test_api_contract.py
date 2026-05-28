from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from app.core.storage import create_paper, create_run, save_final
from app.routers import export as export_router


def _assert_envelope(payload: dict):
    assert isinstance(payload, dict)
    assert {"success", "data", "error"}.issubset(payload.keys())


def _pdf_bytes(text: str = "Demo PDF") -> bytes:
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buffer.getvalue()


def test_health_returns_enveloped_success(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    _assert_envelope(payload)
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["ok"] is True


def test_ingest_json_returns_paper_id_in_data(client: TestClient):
    resp = client.post("/ingest", json={"url": "https://arxiv.org/abs/1706.03762"})
    assert resp.status_code == 200
    payload = resp.json()
    _assert_envelope(payload)
    assert payload["success"] is True
    assert payload["data"]["paper_id"]
    assert payload["data"]["source_type"] == "url"


def test_ingest_pdf_upload_returns_paper_id_in_data(client: TestClient):
    files = {"file": ("demo.pdf", _pdf_bytes(), "application/pdf")}
    resp = client.post("/ingest", files=files)
    assert resp.status_code == 200
    payload = resp.json()
    _assert_envelope(payload)
    assert payload["success"] is True
    assert payload["data"]["paper_id"]
    assert payload["data"]["source_type"] == "upload"


def test_analyze_returns_404_for_missing_paper(client: TestClient):
    resp = client.post("/analyze", json={"paper_id": "missing-paper-id", "mode": "deep"})
    assert resp.status_code == 404
    payload = resp.json()
    _assert_envelope(payload)
    assert payload["success"] is False
    assert payload["error"]["code"] == 404
    assert payload["error"]["message"] == "paper not found"


def test_report_returns_404_when_run_has_no_outputs(client: TestClient):
    paper = create_paper(source_type="url", source_name="https://example.com/paper")
    create_run(paper_id=paper["id"], mode="deep")

    resp = client.get(f"/report/{paper['id']}")
    assert resp.status_code == 404
    payload = resp.json()
    _assert_envelope(payload)
    assert payload["success"] is False
    assert payload["error"]["code"] == 404
    assert payload["error"]["message"] == "no report data"


def test_export_pdf_returns_binary_pdf(client: TestClient, monkeypatch):
    monkeypatch.setattr(export_router, "_markdown_to_pdf_bytes", lambda _text: b"%PDF-1.4\nmock\n")

    paper = create_paper(source_type="url", source_name="https://example.com/paper")
    run = create_run(paper_id=paper["id"], mode="deep")
    save_final(
        run["id"],
        {
            "paper_meta": {"title": "Demo Paper", "authors": [], "year": "2026", "source_type": "url"},
            "three_minute_summary": {
                "problem": "demo",
                "method_points": ["point"],
                "key_results": ["result"],
                "limitations": ["limit"],
                "who_should_read": "reader",
            },
            "teach_classmate": {"elevator_30s": "demo", "classroom_3min": "demo", "analogy": "demo", "qa": []},
            "reproduction_guide": {
                "environment": "python",
                "dataset": "demo",
                "commands": ["python run.py"],
                "key_hyperparams": ["lr=1e-4"],
                "expected_range": "ok",
                "common_errors": ["none"],
            },
            "reading_qa": {
                "q1_problem_and_novelty": "demo",
                "q2_related_work_and_researchers": "demo",
                "q3_key_idea": "demo",
                "q4_experiment_design": "demo",
                "q5_dataset_and_code": "demo",
                "q6_support_for_claims": "demo",
                "q7_contribution_and_next_step": "demo",
            },
            "evidence_refs": [{"claim": "demo", "section": "ABSTRACT"}],
            "change_log": [],
        },
    )

    resp = client.get(f"/export/{paper['id']}.pdf")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/pdf")
    assert resp.content.startswith(b"%PDF")


def test_rag_query_returns_citations_and_debug(client: TestClient, tmp_path):
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "rag-demo.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(72, 720, "Transformer attention uses query key value vectors for sequence modeling.")
    c.drawString(72, 700, "Ablation results show attention improves translation quality.")
    c.showPage()
    c.save()

    paper = create_paper(
        source_type="upload",
        source_name="rag-demo.pdf",
        local_pdf_path=str(pdf_path),
        title="RAG Demo",
    )

    resp = client.post(
        "/rag/query",
        json={
            "paper_id": paper["id"],
            "question": "What improves translation quality?",
            "top_k": 3,
            "chunk_size": 400,
            "chunk_overlap": 40,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    _assert_envelope(payload)
    data = payload["data"]
    assert data["answer"]
    assert "根据当前检索到的原文片段" in data["answer"]
    assert data["answer_mode"] == "fallback"
    assert data["citations"]
    assert data["debug"]["chunk_count"] >= 1
    assert data["debug"]["matched_chunk_count"] >= 1
    assert data["debug"]["query_token_count"] >= 1
    assert data["debug"]["generation"] == {"requested": False, "used": False, "reason": "disabled"}
    assert data["debug"]["top_chunks"][0]["page_start"] == 1


def test_rag_query_reports_no_hits_without_mojibake(client: TestClient, tmp_path):
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "rag-no-hit.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(72, 720, "Transformer attention uses query key value vectors for sequence modeling.")
    c.showPage()
    c.save()

    paper = create_paper(
        source_type="upload",
        source_name="rag-no-hit.pdf",
        local_pdf_path=str(pdf_path),
        title="RAG No Hit",
    )

    resp = client.post(
        "/rag/query",
        json={
            "paper_id": paper["id"],
            "question": "unrelatedbiologyterm",
            "top_k": 3,
            "chunk_size": 400,
            "chunk_overlap": 40,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer"] == "资料中没有检索到足够相关的片段，当前问题建议人工核查原文后再回答。"
    assert "璧勬枡" not in data["answer"]
    assert data["citations"] == []
    assert data["debug"]["matched_chunk_count"] == 0
    assert data["debug"]["generation"] == {"requested": False, "used": False, "reason": "no_hits"}
