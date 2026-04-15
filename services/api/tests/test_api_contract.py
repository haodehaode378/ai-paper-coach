from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.storage import create_paper, create_run


def _assert_envelope(payload: dict):
    assert isinstance(payload, dict)
    assert {"success", "data", "error"}.issubset(payload.keys())


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
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    files = {"file": ("demo.pdf", pdf_content, "application/pdf")}
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
