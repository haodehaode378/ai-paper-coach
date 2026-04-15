from __future__ import annotations


def test_api_key_auth_requires_valid_key(client_factory):
    with client_factory({"APC_REQUIRE_API_KEY": "1", "APC_API_KEY": "secret-key"}) as client:
        denied = client.post("/ingest", json={"url": "https://arxiv.org/abs/1706.03762"})
        denied_payload = denied.json()
        assert denied.status_code == 401
        assert denied_payload["success"] is False
        assert denied_payload["error"]["code"] == 401

        allowed = client.post(
            "/ingest",
            json={"url": "https://arxiv.org/abs/1706.03762"},
            headers={"x-api-key": "secret-key"},
        )
        allowed_payload = allowed.json()
        assert allowed.status_code == 200
        assert allowed_payload["success"] is True
        assert allowed_payload["data"]["paper_id"]


def test_upload_size_limit_returns_413(client_factory):
    with client_factory({"APC_MAX_UPLOAD_MB": "0.00005"}) as client:
        big_pdf = b"%PDF-1.4\n" + (b"a" * 80_000)
        files = {"file": ("big.pdf", big_pdf, "application/pdf")}
        resp = client.post("/ingest", files=files)
        payload = resp.json()
        assert resp.status_code == 413
        assert payload["success"] is False
        assert payload["error"]["code"] == 413


def test_cors_uses_allowed_origins_whitelist(client_factory):
    with client_factory({"APC_ALLOWED_ORIGINS": "http://localhost:5500,http://example.com"}) as client:
        allowed = client.options(
            "/ingest",
            headers={
                "Origin": "http://localhost:5500",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5500"

        blocked = client.options(
            "/ingest",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert blocked.status_code == 400
        assert blocked.headers.get("access-control-allow-origin") is None
