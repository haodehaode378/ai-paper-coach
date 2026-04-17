from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from app.core.model_router import ModelRouter

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
REQUIRED_QA_KEYS = [
    "q1_problem_and_novelty",
    "q2_related_work_and_researchers",
    "q3_key_idea",
    "q4_experiment_design",
    "q5_dataset_and_code",
    "q6_support_for_claims",
    "q7_contribution_and_next_step",
]
QUESTION_TEXTS = {
    "q1_problem_and_novelty": "1 论文试图解决什么问题？这是否是一个新的问题？",
    "q2_related_work_and_researchers": "2 有哪些相关研究？如何归类？谁是这一课题在领域内值得关注的研究者（公司）？",
    "q3_key_idea": "3 论文中提到的解决方案之关键是什么？",
    "q4_experiment_design": "4 论文中的实验是如何设计的？",
    "q5_dataset_and_code": "5 用于定量评估的数据集是什么？代码有没有开源？",
    "q6_support_for_claims": "6 文中的实验及结果有没有很好地支持需要验证的科学假设/提出方案？",
    "q7_contribution_and_next_step": "7 这篇论文到底有什么贡献？下一步呢？有什么工作可以继续深入？",
}


def _load(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _mock_draft(chunks: list[dict[str, str]], source_type: str, failure_reason: str | None = None) -> dict[str, Any]:
    joined = "\n\n".join([f"[{c['section']}]\n{c['content']}" for c in chunks])
    snippet = " ".join(joined.split())[:900]
    reading_qa = {
        "q1_problem_and_novelty": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q2_related_work_and_researchers": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q3_key_idea": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q4_experiment_design": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q5_dataset_and_code": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q6_support_for_claims": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
        "q7_contribution_and_next_step": "论文中未明确说明。当前为降级输出，建议恢复模型后再补全长答。",
    }
    return {
        "paper_meta": {
            "title": "Unknown Title",
            "authors": [],
            "year": "",
            "source_type": source_type,
        },
        "three_minute_summary": {
            "problem": "模型不可用，当前仅生成降级版结构化草稿。请在模型恢复后执行 review 与 finalize 获取完整长文分析。",
            "method_points": ["已完成切片读取与章节级信息汇总。", "已构建可供后续问答与整合的基础结构。"],
            "key_results": ["当前降级模式不保证实验细节完整。"],
            "limitations": ["未完成模型推理，内容仅作占位。"],
            "who_should_read": "适合作为后续精读流程的中间底稿。",
        },
        "teach_classmate": {
            "elevator_30s": "这是一份降级草稿，真实结论需要模型恢复后生成。",
            "classroom_3min": snippet,
            "analogy": "可以把当前结果理解为把论文做成了目录化证据清单，后续再填充完整讲解。",
            "qa": [],
        },
        "reproduction_guide": {
            "environment": "论文中未明确说明。",
            "dataset": "论文中未明确说明。",
            "commands": ["论文中未明确说明"],
            "key_hyperparams": ["论文中未明确说明"],
            "expected_range": "论文中未明确说明。",
            "common_errors": ["模型调用失败，建议先恢复 API 连通性。"],
        },
        "reading_qa": reading_qa,
        "evidence_refs": [{"claim": "降级模式草稿", "section": chunks[0]["section"] if chunks else "FULL_TEXT"}],
        "change_log": ([f"模型调用失败，已降级到本地模式：{failure_reason[:300]}"] if failure_reason else []),
    }


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _text_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.strip())
    if isinstance(value, list):
        return sum(_text_len(item) for item in value)
    if isinstance(value, dict):
        return sum(_text_len(v) for v in value.values())
    return len(str(value).strip())


def _normalize_evidence_refs(raw: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                claim = str(item.get("claim", "")).strip()
                section = str(item.get("section", "")).strip()
                if claim or section:
                    refs.append({"claim": claim or "论文中未明确说明", "section": section or "论文中未明确说明"})
            elif isinstance(item, str) and item.strip():
                refs.append({"claim": item.strip(), "section": "论文中未明确说明"})
    return refs


def _merge_evidence_refs(*groups: Any, limit: int = 40) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for g in groups:
        for item in _normalize_evidence_refs(g):
            key = (item["claim"], item["section"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def get_requirement_issues(report: dict[str, Any]) -> list[str]:
    summary = report.get("three_minute_summary", {})
    repro = report.get("reproduction_guide", {})
    reading_qa = report.get("reading_qa", {})

    text_fields = [
        str(summary.get("problem", "")),
        str(repro.get("environment", "")),
        str(repro.get("dataset", "")),
    ]

    issues: list[str] = []
    if any("Not explicitly stated in paper" in item for item in text_fields):
        issues.append("包含英文兜底短语 Not explicitly stated in paper")
    if any(item and not _contains_chinese(item) for item in text_fields):
        issues.append("关键文本字段存在非中文内容")

    for arr_key in ("method_points", "key_results", "limitations"):
        if not summary.get(arr_key):
            issues.append(f"three_minute_summary.{arr_key} 为空")

    problem_len = _text_len(summary.get("problem", ""))
    if problem_len < 800:
        issues.append(f"three_minute_summary.problem 字数不足（{problem_len}/800）")

    repro_total = (
        _text_len(repro.get("environment", ""))
        + _text_len(repro.get("dataset", ""))
        + _text_len(repro.get("commands", []))
        + _text_len(repro.get("key_hyperparams", []))
        + _text_len(repro.get("expected_range", ""))
        + _text_len(repro.get("common_errors", []))
    )
    if repro_total < 1000:
        issues.append(f"reproduction_guide 总字数不足（{repro_total}/1000）")

    if not isinstance(reading_qa, dict):
        issues.append("reading_qa 不是对象")
        return issues

    for key in REQUIRED_QA_KEYS:
        content = str(reading_qa.get(key, "")).strip()
        length = _text_len(content)
        if not content:
            issues.append(f"{key} 为空")
            continue
        if length < 700:
            issues.append(f"{key} 字数不足（{length}/700）")

    refs = _normalize_evidence_refs(report.get("evidence_refs"))
    if len(refs) < 12:
        issues.append(f"evidence_refs 数量不足（{len(refs)}/12）")

    return issues


def _needs_repair(report: dict[str, Any]) -> bool:
    return bool(get_requirement_issues(report))


def normalize_report(payload: dict[str, Any], source_type: str = "url") -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    summary_leaf_keys = {"problem", "method_points", "key_results", "limitations", "who_should_read"}
    repro_leaf_keys = {"environment", "dataset", "commands", "key_hyperparams", "expected_range", "common_errors"}
    if payload and set(payload.keys()).issubset(summary_leaf_keys) and ("problem" in payload or "method_points" in payload):
        payload = {"three_minute_summary": payload}
    elif payload and set(payload.keys()).issubset(repro_leaf_keys) and ("environment" in payload or "commands" in payload):
        payload = {"reproduction_guide": payload}

    if "draft" in payload and isinstance(payload.get("draft"), dict):
        payload = payload["draft"]

    paper_meta = payload.get("paper_meta")
    if not isinstance(paper_meta, dict):
        paper_meta = {}

    summary = payload.get("three_minute_summary")
    if isinstance(summary, str):
        summary = {
            "problem": summary,
            "method_points": [],
            "key_results": [],
            "limitations": [],
            "who_should_read": "",
        }
    elif not isinstance(summary, dict):
        summary = {}

    teach = payload.get("teach_classmate")
    if isinstance(teach, str):
        teach = {
            "elevator_30s": teach,
            "classroom_3min": "",
            "analogy": "",
            "qa": [],
        }
    elif not isinstance(teach, dict):
        teach = {}

    repro = payload.get("reproduction_guide")
    if isinstance(repro, str):
        repro = {
            "environment": "",
            "dataset": "",
            "commands": [repro],
            "key_hyperparams": [],
            "expected_range": "",
            "common_errors": [],
        }
    elif not isinstance(repro, dict):
        repro = {}

    reading_qa = payload.get("reading_qa")
    if not isinstance(reading_qa, dict):
        reading_qa = {}

    normalized = {
        "paper_meta": {
            "title": str(paper_meta.get("title", "")),
            "authors": _as_list(paper_meta.get("authors")),
            "year": str(paper_meta.get("year", "")) if paper_meta.get("year") is not None else "",
            "source_type": paper_meta.get("source_type", source_type),
        },
        "three_minute_summary": {
            "problem": str(summary.get("problem", "")),
            "method_points": _as_list(summary.get("method_points")),
            "key_results": _as_list(summary.get("key_results")),
            "limitations": _as_list(summary.get("limitations")),
            "who_should_read": str(summary.get("who_should_read", "")),
        },
        "teach_classmate": {
            "elevator_30s": str(teach.get("elevator_30s", "")),
            "classroom_3min": str(teach.get("classroom_3min", "")),
            "analogy": str(teach.get("analogy", "")),
            "qa": _as_list(teach.get("qa")),
        },
        "reproduction_guide": {
            "environment": str(repro.get("environment", "")),
            "dataset": str(repro.get("dataset", "")),
            "commands": _as_list(repro.get("commands")),
            "key_hyperparams": _as_list(repro.get("key_hyperparams")),
            "expected_range": str(repro.get("expected_range", "")),
            "common_errors": _as_list(repro.get("common_errors")),
        },
        "reading_qa": {
            "q1_problem_and_novelty": str(reading_qa.get("q1_problem_and_novelty", "")),
            "q2_related_work_and_researchers": str(reading_qa.get("q2_related_work_and_researchers", "")),
            "q3_key_idea": str(reading_qa.get("q3_key_idea", "")),
            "q4_experiment_design": str(reading_qa.get("q4_experiment_design", "")),
            "q5_dataset_and_code": str(reading_qa.get("q5_dataset_and_code", "")),
            "q6_support_for_claims": str(reading_qa.get("q6_support_for_claims", "")),
            "q7_contribution_and_next_step": str(reading_qa.get("q7_contribution_and_next_step", "")),
        },
        "evidence_refs": _normalize_evidence_refs(payload.get("evidence_refs")),
        "change_log": _as_list(payload.get("change_log")),
    }

    return normalized


def _normalize_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    reading_qa = payload.get("reading_qa") if isinstance(payload.get("reading_qa"), dict) else {}
    normalized = {
        "reading_qa": {
            "q1_problem_and_novelty": str(reading_qa.get("q1_problem_and_novelty", "")),
            "q2_related_work_and_researchers": str(reading_qa.get("q2_related_work_and_researchers", "")),
            "q3_key_idea": str(reading_qa.get("q3_key_idea", "")),
            "q4_experiment_design": str(reading_qa.get("q4_experiment_design", "")),
            "q5_dataset_and_code": str(reading_qa.get("q5_dataset_and_code", "")),
            "q6_support_for_claims": str(reading_qa.get("q6_support_for_claims", "")),
            "q7_contribution_and_next_step": str(reading_qa.get("q7_contribution_and_next_step", "")),
        },
        "evidence_refs": _normalize_evidence_refs(payload.get("evidence_refs")),
        "change_log": _as_list(payload.get("change_log")),
        "review_skipped": bool(payload.get("review_skipped", False)),
        "reason": str(payload.get("reason", "")),
    }
    return normalized


def _review_lengths_ok(review_payload: dict[str, Any]) -> bool:
    reading_qa = review_payload.get("reading_qa", {}) if isinstance(review_payload, dict) else {}
    if not isinstance(reading_qa, dict):
        return False
    return all(_text_len(reading_qa.get(key, "")) >= 700 for key in REQUIRED_QA_KEYS)


def _render_chunk_context(chunks: list[dict[str, str]], max_chars: int = 12000) -> str:
    parts: list[str] = []
    total = 0
    for item in chunks:
        section = str(item.get("section", "")).strip() or "UNKNOWN"
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        block = f"[{section}]\n{content}\n"
        if total + len(block) > max_chars:
            remain = max_chars - total
            if remain <= 0:
                break
            block = block[:remain]
        parts.append(block)
        total += len(block)
        if total >= max_chars:
            break
    return "\n".join(parts)


def _synthesize_missing_review_answers(
    *,
    router: ModelRouter,
    draft: dict[str, Any],
    chunks: list[dict[str, str]],
    seed_review: dict[str, Any] | None = None,
    force_all: bool = False,
) -> dict[str, Any]:
    seeded = _normalize_review_payload(seed_review or {})
    reading_qa = copy.deepcopy(seeded.get("reading_qa", {}))
    evidence_refs = _normalize_evidence_refs(seeded.get("evidence_refs"))
    chunk_context = _render_chunk_context(chunks)
    draft_summary = str((draft.get("three_minute_summary") or {}).get("problem", ""))
    draft_meta = draft.get("paper_meta", {})
    change_log = list(seeded.get("change_log", []))
    errors: list[str] = []
    filled_keys: list[str] = []

    system = (
        "你是论文问答补全器。你每次只回答一个问题。"
        "请严格基于给定论文切片输出中文长答，并只输出一个合法 JSON 对象。"
        "JSON 键严格为 answer, evidence_refs。"
        "要求："
        "1. answer 必须 >=700字；"
        "2. 不编造；无依据写“论文中未明确说明”；"
        "3. 正文中必须显式写“（见 section: XXX）”；"
        "4. evidence_refs 至少 2 条，每条含 claim 和 section；"
        "5. 不要输出 markdown、代码块或解释文本。"
    )

    for key in REQUIRED_QA_KEYS:
        if not force_all and _text_len(reading_qa.get(key, "")) >= 700:
            continue
        user = json.dumps(
            {
                "paper_meta": draft_meta,
                "draft_problem": draft_summary,
                "question_key": key,
                "question": QUESTION_TEXTS[key],
                "chunks": chunk_context,
            },
            ensure_ascii=False,
        )
        answered = False
        for provider in ("secondary", "primary"):
            try:
                raw = getattr(router, provider)(system=system, user=user)
                answer = str(raw.get("answer", "")).strip() if isinstance(raw, dict) else ""
                refs = _normalize_evidence_refs(raw.get("evidence_refs")) if isinstance(raw, dict) else []
                if _text_len(answer) < 700:
                    raise RuntimeError("single_question_too_short")
                reading_qa[key] = answer
                evidence_refs = _merge_evidence_refs(evidence_refs, refs, limit=50)
                filled_keys.append(key)
                answered = True
                break
            except Exception as e:
                errors.append(f"{QUESTION_TEXTS[key]}::{_provider_label(router, provider)}={str(e)}")
        if not answered and key not in reading_qa:
            reading_qa[key] = ""

    if filled_keys:
        change_log.append(f"阶段2补救：逐题补全成功 {len(filled_keys)} 题")
    if errors:
        change_log.append(f"阶段2补救失败记录：{' | '.join(errors)[:1200]}")

    return {
        "reading_qa": reading_qa,
        "evidence_refs": evidence_refs,
        "change_log": change_log,
        "review_skipped": not all(_text_len(reading_qa.get(key, "")) >= 700 for key in REQUIRED_QA_KEYS),
        "reason": "",
    }


def _append_change_log(report: dict[str, Any], message: str) -> None:
    logs = report.get("change_log")
    if not isinstance(logs, list):
        logs = []
    logs.append(message)
    report["change_log"] = logs


def _append_requirement_issues(report: dict[str, Any], phase: str) -> None:
    issues = get_requirement_issues(report)
    if not issues:
        return
    joined = "；".join(issues)
    _append_change_log(report, f"{phase}存在未达标项：{joined[:1200]}")


def _is_degenerate_draft(report: dict[str, Any]) -> bool:
    summary = report.get("three_minute_summary", {}) if isinstance(report, dict) else {}
    reading_qa = report.get("reading_qa", {}) if isinstance(report, dict) else {}
    evidence_refs = report.get("evidence_refs", []) if isinstance(report, dict) else []
    method_points = summary.get("method_points", []) if isinstance(summary, dict) else []

    qa_total = 0
    if isinstance(reading_qa, dict):
        qa_total = sum(_text_len(reading_qa.get(key, "")) for key in REQUIRED_QA_KEYS)

    return (
        _text_len(summary.get("problem", "")) == 0
        and qa_total == 0
        and _text_len(method_points) == 0
        and len(_normalize_evidence_refs(evidence_refs)) == 0
    )


def _is_degenerate_finalize_report(report: dict[str, Any]) -> bool:
    if not isinstance(report, dict):
        return True
    summary = report.get("three_minute_summary", {}) if isinstance(report.get("three_minute_summary"), dict) else {}
    repro = report.get("reproduction_guide", {}) if isinstance(report.get("reproduction_guide"), dict) else {}
    summary_signal = (
        _text_len(summary.get("problem", ""))
        + _text_len(summary.get("method_points", []))
        + _text_len(summary.get("key_results", []))
        + _text_len(summary.get("limitations", []))
    )
    repro_signal = (
        _text_len(repro.get("environment", ""))
        + _text_len(repro.get("dataset", ""))
        + _text_len(repro.get("commands", []))
        + _text_len(repro.get("key_hyperparams", []))
        + _text_len(repro.get("expected_range", ""))
        + _text_len(repro.get("common_errors", []))
    )
    return summary_signal == 0 and repro_signal == 0


def _merge_reproduction_guide(
    current: dict[str, Any] | None,
    fallback: dict[str, Any] | None,
) -> dict[str, Any]:
    cur = current if isinstance(current, dict) else {}
    fb = fallback if isinstance(fallback, dict) else {}

    def _pick_text(key: str) -> str:
        left = str(cur.get(key, "")).strip()
        if left:
            return left
        return str(fb.get(key, "")).strip()

    def _pick_list(key: str) -> list[Any]:
        left = _as_list(cur.get(key))
        if any(_text_len(item) > 0 for item in left):
            return left
        return _as_list(fb.get(key))

    return {
        "environment": _pick_text("environment"),
        "dataset": _pick_text("dataset"),
        "commands": _pick_list("commands"),
        "key_hyperparams": _pick_list("key_hyperparams"),
        "expected_range": _pick_text("expected_range"),
        "common_errors": _pick_list("common_errors"),
    }


def _provider_label(router: ModelRouter, slot: str) -> str:
    info = router.provider_info(slot)
    name = str(info.get("name") or slot)
    return f"{name}({slot})"


def _emit_orchestrator_trace(trace_hook: Any | None, *, phase: str, event: str, payload: dict[str, Any]) -> None:
    if not trace_hook:
        return
    try:
        trace_hook(
            {
                "phase": phase,
                "provider_slot": "orchestrator",
                "provider_name": "orchestrator",
                "model": "-",
                "request_system": event,
                "request_user": "",
                "response_text": None,
                "error_text": None,
                "meta": payload,
            }
        )
    except Exception:
        return


def repair_report(
    *,
    report: dict[str, Any],
    chunks: list[dict[str, str]],
    model_config: dict[str, Any] | None = None,
    trace_hook: Any | None = None,
) -> dict[str, Any]:
    router = ModelRouter(model_config=model_config, trace_hook=trace_hook, trace_phase="repair")
    system = _load("repair_qwen.txt")
    user = json.dumps({"report": report, "chunks": chunks}, ensure_ascii=False)

    errors: list[str] = []
    for provider in ("primary", "secondary"):
        try:
            raw = getattr(router, provider)(system=system, user=user)
            fixed = normalize_report(raw, source_type=report.get("paper_meta", {}).get("source_type", "url"))
            fixed["paper_meta"] = copy.deepcopy(report.get("paper_meta", fixed.get("paper_meta", {})))
            fixed["evidence_refs"] = _merge_evidence_refs(report.get("evidence_refs"), fixed.get("evidence_refs"), limit=40)
            if chunks and not _review_lengths_ok({"reading_qa": fixed.get("reading_qa", {})}):
                rescued = _synthesize_missing_review_answers(
                    router=router,
                    draft=fixed,
                    chunks=chunks,
                    seed_review={"reading_qa": fixed.get("reading_qa", {}), "evidence_refs": fixed.get("evidence_refs", [])},
                )
                fixed["reading_qa"] = rescued.get("reading_qa", fixed.get("reading_qa", {}))
                fixed["evidence_refs"] = _merge_evidence_refs(fixed.get("evidence_refs"), rescued.get("evidence_refs"), limit=40)
                fixed["change_log"] = _as_list(fixed.get("change_log")) + _as_list(rescued.get("change_log"))
            _append_change_log(fixed, f"修复阶段使用模型：{_provider_label(router, provider)}")
            if errors:
                _append_change_log(fixed, f"模型调用失败，已切换：{' | '.join(errors)[:300]}")
            issues = get_requirement_issues(fixed)
            if issues:
                errors.append(f"{_provider_label(router, provider)}=修复后仍有未达标项")
                _append_requirement_issues(fixed, "修复阶段")
                continue
            return fixed
        except Exception as e:
            errors.append(f"{_provider_label(router, provider)}={str(e)}")

    _append_change_log(report, f"repair阶段模型调用失败或结果未达标，保持原稿：{' | '.join(errors)[:300]}")
    _append_requirement_issues(report, "repair失败后")
    return report


def generate_draft(
    *,
    chunks: list[dict[str, str]],
    source_type: str,
    model_config: dict[str, Any] | None = None,
    trace_hook: Any | None = None,
) -> dict[str, Any]:
    router = ModelRouter(model_config=model_config, trace_hook=trace_hook, trace_phase="analyze")
    system = _load("draft_qwen.txt")
    user = json.dumps({"chunks": chunks, "source_type": source_type}, ensure_ascii=False)

    errors: list[str] = []
    for provider in ("primary", "secondary"):
        try:
            raw = getattr(router, provider)(system=system, user=user)
            report = normalize_report(raw, source_type=source_type)
            if _is_degenerate_draft(report):
                raise RuntimeError("degenerate_draft_output")
            report["evidence_refs"] = _merge_evidence_refs(report.get("evidence_refs"), limit=40)
            _append_change_log(report, f"阶段1（证据底稿）使用模型：{_provider_label(router, provider)}")
            if errors:
                _append_change_log(report, f"模型调用失败，已切换：{' | '.join(errors)[:300]}")
            _append_requirement_issues(report, "阶段1输出")
            return report
        except Exception as e:
            errors.append(f"{_provider_label(router, provider)}={str(e)}")

    report = _mock_draft(chunks, source_type, failure_reason=" | ".join(errors))
    _append_requirement_issues(report, "降级输出")
    return report


def review_draft(
    *,
    draft: dict[str, Any],
    chunks: list[dict[str, str]],
    model_config: dict[str, Any] | None = None,
    trace_hook: Any | None = None,
) -> dict[str, Any]:
    router = ModelRouter(model_config=model_config, trace_hook=trace_hook, trace_phase="review")
    rescued = _synthesize_missing_review_answers(
        router=router,
        draft=draft,
        chunks=chunks,
        seed_review=None,
        force_all=True,
    )
    rescued["evidence_refs"] = _merge_evidence_refs(draft.get("evidence_refs"), rescued.get("evidence_refs"), limit=40)
    if _review_lengths_ok(rescued):
        rescued["review_skipped"] = False
        rescued["reason"] = ""
        rescued["change_log"].append("阶段2：7问采用逐题生成模式并达到长答要求")
        return _normalize_review_payload(rescued)

    fallback = {
        "reading_qa": copy.deepcopy(draft.get("reading_qa", {})),
        "evidence_refs": _merge_evidence_refs(draft.get("evidence_refs"), limit=40),
        "change_log": _as_list(rescued.get("change_log")) + ["阶段2失败，回退使用阶段1问答。"],
        "review_skipped": True,
        "reason": "Review API unavailable",
    }
    return _normalize_review_payload(fallback)


def patch_draft(
    *,
    draft: dict[str, Any],
    review: dict[str, Any],
    context: dict[str, Any] | None = None,
    strict: bool = False,
    model_config: dict[str, Any] | None = None,
    trace_hook: Any | None = None,
) -> dict[str, Any]:
    router = ModelRouter(model_config=model_config, trace_hook=trace_hook, trace_phase="finalize")
    system = _load("patch_qwen.txt")
    user = json.dumps({"draft": draft, "review": review, "context": context or {}}, ensure_ascii=False)

    errors: list[str] = []
    repair_chunks = []
    if isinstance(context, dict) and isinstance(context.get("chunks"), list):
        repair_chunks = context.get("chunks") or []
    _emit_orchestrator_trace(
        trace_hook,
        phase="finalize",
        event="finalize_started",
        payload={
            "strict": bool(strict),
            "repair_chunk_count": len(repair_chunks),
        },
    )
    for provider in ("primary", "secondary"):
        try:
            repair_triggered = False
            patched_raw = getattr(router, provider)(system=system, user=user)
            patched = normalize_report(patched_raw, source_type=draft.get("paper_meta", {}).get("source_type", "url"))
            patched["paper_meta"] = copy.deepcopy(draft.get("paper_meta", patched.get("paper_meta", {})))
            patched["reproduction_guide"] = _merge_reproduction_guide(
                patched.get("reproduction_guide"),
                draft.get("reproduction_guide"),
            )
            patched["reading_qa"] = {
                **patched.get("reading_qa", {}),
                **_normalize_review_payload(review).get("reading_qa", {}),
            }
            patched["evidence_refs"] = _merge_evidence_refs(draft.get("evidence_refs"), review.get("evidence_refs"), patched.get("evidence_refs"), limit=50)
            if repair_chunks and not _review_lengths_ok({"reading_qa": patched.get("reading_qa", {})}):
                rescued = _synthesize_missing_review_answers(
                    router=router,
                    draft=patched,
                    chunks=repair_chunks,
                    seed_review={"reading_qa": patched.get("reading_qa", {}), "evidence_refs": patched.get("evidence_refs", [])},
                )
                patched["reading_qa"] = rescued.get("reading_qa", patched.get("reading_qa", {}))
                patched["evidence_refs"] = _merge_evidence_refs(patched.get("evidence_refs"), rescued.get("evidence_refs"), limit=50)
                patched["change_log"] = _as_list(patched.get("change_log")) + _as_list(rescued.get("change_log"))
            if _is_degenerate_finalize_report(patched):
                raise RuntimeError("degenerate_finalize_output")
            _append_change_log(patched, f"阶段3（最终整合）使用模型：{_provider_label(router, provider)}")
            if errors:
                _append_change_log(patched, f"模型调用失败，已切换：{' | '.join(errors)[:300]}")

            if _needs_repair(patched):
                repair_triggered = True
                logger.info(
                    "finalize_repair_triggered provider=%s strict=%s",
                    _provider_label(router, provider),
                    bool(strict),
                )
                _emit_orchestrator_trace(
                    trace_hook,
                    phase="finalize",
                    event="finalize_repair_triggered",
                    payload={
                        "provider": _provider_label(router, provider),
                        "strict": bool(strict),
                    },
                )
                patched = repair_report(report=patched, chunks=repair_chunks, model_config=model_config, trace_hook=trace_hook)
                patched["reproduction_guide"] = _merge_reproduction_guide(
                    patched.get("reproduction_guide"),
                    draft.get("reproduction_guide"),
                )
            _append_requirement_issues(patched, "阶段3输出")
            issue_count = len(get_requirement_issues(patched))
            logger.info(
                "finalize_completed provider=%s strict=%s repair_triggered=%s issue_count=%s",
                _provider_label(router, provider),
                bool(strict),
                repair_triggered,
                issue_count,
            )
            _emit_orchestrator_trace(
                trace_hook,
                phase="finalize",
                event="finalize_completed",
                payload={
                    "provider": _provider_label(router, provider),
                    "strict": bool(strict),
                    "repair_triggered": repair_triggered,
                    "issue_count": issue_count,
                },
            )
            return patched
        except Exception as e:
            errors.append(f"{_provider_label(router, provider)}={str(e)}")
            logger.warning("finalize_provider_failed provider=%s error=%s", _provider_label(router, provider), str(e))

    fallback = copy.deepcopy(draft)
    rev = _normalize_review_payload(review)
    fallback["reading_qa"] = {**fallback.get("reading_qa", {}), **rev.get("reading_qa", {})}
    fallback["evidence_refs"] = _merge_evidence_refs(fallback.get("evidence_refs"), rev.get("evidence_refs"), limit=50)
    _append_change_log(fallback, f"阶段3模型调用失败，使用回退整合：{' | '.join(errors)[:500]}")
    if strict:
        _append_change_log(fallback, "strict=true：请人工复核关键结论与证据映射。")
    _append_requirement_issues(fallback, "阶段3回退输出")
    _emit_orchestrator_trace(
        trace_hook,
        phase="finalize",
        event="finalize_fallback",
        payload={
            "strict": bool(strict),
            "errors": errors[:10],
        },
    )
    return fallback


def to_markdown(report: dict[str, Any]) -> str:
    s = report.get("three_minute_summary", {})
    t = report.get("teach_classmate", {})
    r = report.get("reproduction_guide", {})
    q = report.get("reading_qa", {})

    def bullets(items: list[Any]) -> str:
        if not items:
            return "-"
        return "\n".join([f"- {x}" for x in items])

    qa_blocks = [
        ("q1_problem_and_novelty", "1 论文试图解决什么问题？这是否是一个新的问题？"),
        ("q2_related_work_and_researchers", "2 有哪些相关研究？如何归类？谁是这一课题在领域内值得关注的研究者（公司）？"),
        ("q3_key_idea", "3 论文中提到的解决方案之关键是什么？"),
        ("q4_experiment_design", "4 论文中的实验是如何设计的？"),
        ("q5_dataset_and_code", "5 用于定量评估的数据集是什么？代码有没有开源？"),
        ("q6_support_for_claims", "6 文中的实验及结果有没有很好地支持需要验证的科学假设/提出方案？"),
        ("q7_contribution_and_next_step", "7 这篇论文到底有什么贡献？下一步呢？有什么工作可以继续深入？"),
    ]

    lines: list[str] = [
        f"# {report.get('paper_meta', {}).get('title', 'Paper Report')}",
        "",
        "## 论文分析（核心）",
        str(s.get("problem", "-") or "-"),
        "",
        "## 方法要点",
        bullets(s.get("method_points", [])),
        "",
        "## 关键结果",
        bullets(s.get("key_results", [])),
        "",
        "## 局限性",
        bullets(s.get("limitations", [])),
        "",
        "## 讲给同学听",
        "### 30秒",
        str(t.get("elevator_30s", "-") or "-"),
        "",
        "### 3分钟",
        str(t.get("classroom_3min", "-") or "-"),
        "",
        "### 类比",
        str(t.get("analogy", "-") or "-"),
        "",
        "## 复现指导",
        "### Environment",
        str(r.get("environment", "-") or "-"),
        "",
        "### Dataset",
        str(r.get("dataset", "-") or "-"),
        "",
        "### Commands",
        bullets(r.get("commands", [])),
        "",
        "### Common Errors",
        bullets(r.get("common_errors", [])),
        "",
        "## 七问",
    ]

    for idx, (key, question) in enumerate(qa_blocks, start=1):
        lines.extend(
            [
                f"### 第{idx}问",
                f"问题：{question}",
                "",
                f"回答：{str(q.get(key, '-') or '-')}",
                "",
            ]
        )

    lines.extend(
        [
            "## Change Log",
            bullets(report.get("change_log", [])),
        ]
    )

    return "\n".join(lines).strip()
