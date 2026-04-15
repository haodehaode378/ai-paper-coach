from __future__ import annotations

from app.core import orchestrator
from app.core.parser import infer_title_from_source
from app.routers import analyze as analyze_router


def test_infer_title_from_arxiv_api(monkeypatch):
    class _Resp:
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry><title> API Title Paper </title></entry>"
            "</feed>"
        )

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("app.core.parser.requests.get", lambda *_args, **_kwargs: _Resp())
    title = infer_title_from_source("url", "https://arxiv.org/abs/1706.03762")
    assert title == "API Title Paper"


def test_infer_title_from_arxiv_html(monkeypatch):
    class _Resp:
        text = '<html><h1 class="title mathjax"><span class="descriptor">Title:</span> Test Paper Title </h1></html>'

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("app.core.parser.requests.get", lambda *_args, **_kwargs: _Resp())
    title = infer_title_from_source("url", "https://arxiv.org/abs/1706.03762")
    assert title == "Test Paper Title"


def test_placeholder_title_detects_chinese_phrase():
    assert analyze_router._is_placeholder_title("\u8bba\u6587\u4e2d\u672a\u660e\u786e\u8bf4\u660e")
    assert analyze_router._is_placeholder_title("\u8bba\u6587\u4e2d\u672a\u660e\u786e\u8bf4\u660e\uff08\u57fa\u4e8e\u5185\u5bb9\u63a8\u65ad\uff09")


def test_finalize_keeps_reproduction_guide_when_model_returns_empty(monkeypatch):
    class _FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def provider_info(slot: str):
            return {"name": slot}

        @staticmethod
        def primary(system: str, user: str):
            return {
                "paper_meta": {"title": "ok", "authors": [], "year": "", "source_type": "url"},
                "three_minute_summary": {
                    "problem": "A" * 1200,
                    "method_points": ["m1"],
                    "key_results": ["k1"],
                    "limitations": ["l1"],
                    "who_should_read": "x",
                },
                "teach_classmate": {"elevator_30s": "x", "classroom_3min": "x" * 320, "analogy": "x" * 260, "qa": []},
                "reproduction_guide": {},
                "reading_qa": {},
                "evidence_refs": [{"claim": "c1", "section": "s1"}] * 15,
                "change_log": [],
            }

        @staticmethod
        def secondary(system: str, user: str):
            return _FakeRouter.primary(system, user)

    monkeypatch.setattr(orchestrator, "ModelRouter", _FakeRouter)

    review_qa = {key: ("Q" * 720) for key in orchestrator.REQUIRED_QA_KEYS}
    draft = {
        "paper_meta": {"title": "Draft", "authors": [], "year": "", "source_type": "url"},
        "three_minute_summary": {
            "problem": "D" * 1200,
            "method_points": ["m"],
            "key_results": ["k"],
            "limitations": ["l"],
            "who_should_read": "r",
        },
        "teach_classmate": {"elevator_30s": "e", "classroom_3min": "c" * 320, "analogy": "a" * 260, "qa": []},
        "reproduction_guide": {
            "environment": "env " * 150,
            "dataset": "dataset " * 120,
            "commands": ["python train.py", "python eval.py"],
            "key_hyperparams": ["lr=1e-4"],
            "expected_range": "acc around 0.9",
            "common_errors": ["oom", "nan loss"],
        },
        "reading_qa": review_qa,
        "evidence_refs": [{"claim": "c", "section": "s"}] * 15,
        "change_log": [],
    }
    review = {"reading_qa": review_qa, "evidence_refs": [{"claim": "c2", "section": "s2"}], "change_log": []}

    final = orchestrator.patch_draft(draft=draft, review=review, context={"chunks": []}, strict=False)
    repro = final["reproduction_guide"]
    assert repro["environment"]
    assert repro["dataset"]
    assert len(repro["commands"]) > 0


def test_problem_threshold_relaxed_to_800():
    base_report = {
        "paper_meta": {"title": "t", "authors": [], "year": "", "source_type": "url"},
        "three_minute_summary": {
            "problem": "P" * 820,
            "method_points": ["m"],
            "key_results": ["k"],
            "limitations": ["l"],
            "who_should_read": "w",
        },
        "teach_classmate": {"elevator_30s": "e", "classroom_3min": "c" * 320, "analogy": "a" * 260, "qa": []},
        "reproduction_guide": {
            "environment": "env " * 120,
            "dataset": "data " * 120,
            "commands": ["cmd1", "cmd2"],
            "key_hyperparams": ["lr=1e-4"],
            "expected_range": "ok",
            "common_errors": ["none"],
        },
        "reading_qa": {key: "Q" * 720 for key in orchestrator.REQUIRED_QA_KEYS},
        "evidence_refs": [{"claim": f"c{i}", "section": "s"} for i in range(12)],
        "change_log": [],
    }

    issues = orchestrator.get_requirement_issues(base_report)
    assert not any("three_minute_summary.problem 字数不足" in item for item in issues)
