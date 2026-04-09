from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.core.model_router import ModelRouter

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


def _load(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _mock_draft(chunks: list[dict[str, str]], source_type: str, failure_reason: str | None = None) -> dict[str, Any]:
    joined = "\n\n".join([f"[{c['section']}]\n{c['content']}" for c in chunks])
    snippet = " ".join(joined.split())[:500]
    return {
        "paper_meta": {
            "title": "Unknown Title",
            "authors": [],
            "year": "",
            "source_type": source_type,
        },
        "three_minute_summary": {
            "problem": "论文已完成解析，但当前走的是本地降级模式，结论仅供初步参考。",
            "method_points": [
                "已从论文文本中抽取主要章节。",
                "已整理为适合学生阅读的结构化摘要。",
                "如需更准确结果，请配置可用模型接口。",
            ],
            "key_results": ["当前降级模式下不保证实验数字提取完整。"],
            "limitations": ["未调用模型接口，结果来自本地启发式整理。"],
            "who_should_read": "适合准备课程汇报或快速过论文主题的学生。",
        },
        "teach_classmate": {
            "elevator_30s": "这篇论文讨论了一个研究问题，并提出了解法；当前内容是根据提取到的章节做的初步整理。",
            "classroom_3min": snippet,
            "analogy": "可以把它理解为先根据目录和重点段落做课堂预习笔记，再进入正式精读。",
            "qa": [
                {"q": "这个摘要能直接当最终结论吗？", "a": "建议把它当初稿，再对照论文原文核验。"},
                {"q": "为什么没有精确分数？", "a": "降级模式不会编造实验指标。"},
            ],
        },
        "reproduction_guide": {
            "environment": "建议 Python 3.10+，如涉及训练可准备 CUDA 环境。",
            "dataset": "论文中未明确说明",
            "commands": ["先查论文配套代码仓库 README", "先复现数据预处理，再跑训练或推理脚本"],
            "key_hyperparams": ["论文中未明确说明"],
            "expected_range": "论文中未明确说明",
            "common_errors": ["依赖缺失", "数据路径配置错误"],
        },
        "reading_qa": {
            "q1_problem_and_novelty": "这篇论文试图解决的核心问题需要结合原文进一步确认；从当前降级模式看，只能判断它关注某个具体研究任务，但是否构成全新问题还需看 related work 对比。",
            "q2_related_work_and_researchers": "论文中未明确说明。建议重点查看 Related Work 部分，按任务设定、模型结构、训练方式三条线梳理，并记录反复出现的作者、实验室或公司。",
            "q3_key_idea": "当前只能确定论文提出了一套解决思路，但关键机制仍建议回到方法章节核对模块设计、输入输出关系和核心假设。",
            "q4_experiment_design": "建议优先查看实验章节中的数据集、对比方法、评价指标、消融实验和可视化案例，以还原完整实验设计。",
            "q5_dataset_and_code": "论文中未明确说明。需要进一步查找数据集名称、附录、项目主页或 GitHub 链接。",
            "q6_support_for_claims": "在没有完整实验表格和可视化结果前，不能严谨判断证据是否充分支持作者结论。",
            "q7_contribution_and_next_step": "当前可以把贡献理解为提出新方法、新基准或新分析视角之一；下一步应结合论文局限性判断可继续深入的数据规模、泛化性和真实场景验证。",
        },
        "evidence_refs": [{"claim": "已生成本地降级摘要", "section": chunks[0]["section"] if chunks else "FULL_TEXT"}],
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


def get_requirement_issues(report: dict[str, Any]) -> list[str]:
    summary = report.get("three_minute_summary", {})
    teach = report.get("teach_classmate", {})
    repro = report.get("reproduction_guide", {})
    reading_qa = report.get("reading_qa", {})

    text_fields = [
        str(summary.get("problem", "")),
        str(teach.get("elevator_30s", "")),
        str(teach.get("classroom_3min", "")),
        str(repro.get("environment", "")),
        str(repro.get("dataset", "")),
    ]

    issues: list[str] = []
    if any("Not explicitly stated in paper" in item for item in text_fields):
        issues.append("包含英文兜底短语 Not explicitly stated in paper")
    if any(item and not _contains_chinese(item) for item in text_fields):
        issues.append("关键文本字段存在非中文内容")
    if not summary.get("method_points"):
        issues.append("three_minute_summary.method_points 为空")
    if not summary.get("key_results"):
        issues.append("three_minute_summary.key_results 为空")
    if not summary.get("limitations"):
        issues.append("three_minute_summary.limitations 为空")
    if not str(teach.get("elevator_30s", "")).strip():
        issues.append("teach_classmate.elevator_30s 为空")
    if not str(teach.get("classroom_3min", "")).strip():
        issues.append("teach_classmate.classroom_3min 为空")

    problem_len = _text_len(summary.get("problem", ""))
    if problem_len < 700:
        issues.append(f"three_minute_summary.problem 字数不足（{problem_len}/700）")

    analogy_len = _text_len(teach.get("analogy", ""))
    if analogy_len < 180:
        issues.append(f"teach_classmate.analogy 字数不足（{analogy_len}/180）")

    repro_total = (
        _text_len(repro.get("environment", ""))
        + _text_len(repro.get("dataset", ""))
        + _text_len(repro.get("commands", []))
        + _text_len(repro.get("key_hyperparams", []))
        + _text_len(repro.get("expected_range", ""))
        + _text_len(repro.get("common_errors", []))
    )
    if repro_total < 350:
        issues.append(f"reproduction_guide 总字数不足（{repro_total}/350）")

    if not isinstance(reading_qa, dict):
        issues.append("reading_qa 不是对象")
        return issues
    for key in REQUIRED_QA_KEYS:
        content = str(reading_qa.get(key, "")).strip()
        length = _text_len(content)
        if not content:
            issues.append(f"{key} 为空")
            continue
        if length < 120:
            issues.append(f"{key} 字数不足（{length}/120）")

    return issues


def _needs_repair(report: dict[str, Any]) -> bool:
    return bool(get_requirement_issues(report))


def normalize_report(payload: dict[str, Any], source_type: str = "url") -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    # Unwrap model responses like {"draft": {...}, "review": {...}}
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
            "title": paper_meta.get("title", "Unknown Title"),
            "authors": _as_list(paper_meta.get("authors")),
            "year": str(paper_meta.get("year", "")) if paper_meta.get("year") is not None else "",
            "source_type": paper_meta.get("source_type", source_type),
        },
        "three_minute_summary": {
            "problem": summary.get("problem", ""),
            "method_points": _as_list(summary.get("method_points")),
            "key_results": _as_list(summary.get("key_results")),
            "limitations": _as_list(summary.get("limitations")),
            "who_should_read": summary.get("who_should_read", ""),
        },
        "teach_classmate": {
            "elevator_30s": teach.get("elevator_30s", ""),
            "classroom_3min": teach.get("classroom_3min", ""),
            "analogy": teach.get("analogy", ""),
            "qa": _as_list(teach.get("qa")),
        },
        "reproduction_guide": {
            "environment": repro.get("environment", ""),
            "dataset": repro.get("dataset", ""),
            "commands": _as_list(repro.get("commands")),
            "key_hyperparams": _as_list(repro.get("key_hyperparams")),
            "expected_range": repro.get("expected_range", ""),
            "common_errors": _as_list(repro.get("common_errors")),
        },
        "reading_qa": {
            "q1_problem_and_novelty": reading_qa.get("q1_problem_and_novelty", ""),
            "q2_related_work_and_researchers": reading_qa.get("q2_related_work_and_researchers", ""),
            "q3_key_idea": reading_qa.get("q3_key_idea", ""),
            "q4_experiment_design": reading_qa.get("q4_experiment_design", ""),
            "q5_dataset_and_code": reading_qa.get("q5_dataset_and_code", ""),
            "q6_support_for_claims": reading_qa.get("q6_support_for_claims", ""),
            "q7_contribution_and_next_step": reading_qa.get("q7_contribution_and_next_step", ""),
        },
        "evidence_refs": _as_list(payload.get("evidence_refs")),
        "change_log": _as_list(payload.get("change_log")),
    }

    return normalized


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
    _append_change_log(report, f"{phase}存在未达标项：{joined[:900]}")


def _provider_label(router: ModelRouter, slot: str) -> str:
    info = router.provider_info(slot)
    name = str(info.get("name") or slot)
    return f"{name}({slot})"


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
            _append_change_log(report, f"分析阶段使用模型：{_provider_label(router, provider)}")
            if errors:
                _append_change_log(report, f"模型调用失败，已切换：{' | '.join(errors)[:300]}")
            if _needs_repair(report):
                report = repair_report(report=report, chunks=chunks, model_config=model_config, trace_hook=trace_hook)
            _append_requirement_issues(report, "分析阶段输出")
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
    system = _load("review_minimax.txt")
    user = json.dumps({"draft": draft, "chunks": chunks}, ensure_ascii=False)

    errors: list[str] = []
    for provider in ("secondary", "primary"):
        try:
            review_data = getattr(router, provider)(system=system, user=user)
            if isinstance(review_data, dict):
                review_data.setdefault("review_skipped", False)
                review_data.setdefault("reason", "")
                if errors:
                    review_data["reason"] = f"primary_failed_switch_to_{_provider_label(router, provider)}: {' | '.join(errors)[:300]}"
            return review_data
        except Exception as e:
            errors.append(f"{_provider_label(router, provider)}={str(e)}")

    return {
        "missing_points": [],
        "unclear_terms": [],
        "risky_claims": [],
        "patch_suggestions": [],
        "review_skipped": True,
        "reason": f"Review API unavailable: {' | '.join(errors)[:500]}",
    }


def _set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = data
    for p in parts[:-1]:
        if p.isdigit() and isinstance(cur, list):
            cur = cur[int(p)]
        else:
            if p not in cur or not isinstance(cur[p], (dict, list)):
                cur[p] = {}
            cur = cur[p]
    last = parts[-1]
    if last.isdigit() and isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append("")
        cur[idx] = value
    else:
        cur[last] = value


def patch_draft(
    *,
    draft: dict[str, Any],
    review: dict[str, Any],
    strict: bool = False,
    model_config: dict[str, Any] | None = None,
    trace_hook: Any | None = None,
) -> dict[str, Any]:
    router = ModelRouter(model_config=model_config, trace_hook=trace_hook, trace_phase="finalize")
    system = _load("patch_qwen.txt")
    user = json.dumps({"draft": draft, "review": review}, ensure_ascii=False)

    errors: list[str] = []
    for provider in ("primary", "secondary"):
        try:
            patched = getattr(router, provider)(system=system, user=user)
            patched = normalize_report(patched, source_type=draft.get("paper_meta", {}).get("source_type", "url"))
            _append_change_log(patched, f"补丁阶段使用模型：{_provider_label(router, provider)}")
            if errors:
                _append_change_log(patched, f"模型调用失败，已切换：{' | '.join(errors)[:300]}")
            if _needs_repair(patched):
                patched = repair_report(report=patched, chunks=[], model_config=model_config, trace_hook=trace_hook)
            _append_requirement_issues(patched, "补丁阶段输出")
            return patched
        except Exception as e:
            errors.append(f"{_provider_label(router, provider)}={str(e)}")

    patched = copy.deepcopy(draft)
    change_log = list(patched.get("change_log", []))
    for item in review.get("patch_suggestions", []):
        path = item.get("path")
        value = item.get("value")
        instruction = item.get("instruction", "")
        if path and value is not None:
            _set_by_path(patched, path, value)
            change_log.append({"path": path, "instruction": instruction or "Applied local patch"})
    if strict and len(review.get("risky_claims", [])) >= 3:
        change_log.append({"path": "system", "instruction": "Strict mode flagged multiple risky claims; manual verification required."})
    change_log.append({"path": "system", "instruction": f"patch阶段模型调用失败，已使用本地降级逻辑：{' | '.join(errors)[:500]}"})
    patched["change_log"] = change_log
    _append_requirement_issues(patched, "本地补丁输出")
    return patched


def to_markdown(report: dict[str, Any]) -> str:
    s = report.get("three_minute_summary", {})
    t = report.get("teach_classmate", {})
    r = report.get("reproduction_guide", {})

    def bullets(items: list[Any]) -> str:
        if not items:
            return "- -"
        out = []
        for x in items:
            out.append(f"- {x}")
        return "\n".join(out)

    return f"""
# {report.get('paper_meta', {}).get('title', 'Paper Report')}

## 3-Minute Summary

### Problem
{s.get('problem', '-')}

### Method Points
{bullets(s.get('method_points', []))}

### Key Results
{bullets(s.get('key_results', []))}

### Limitations
{bullets(s.get('limitations', []))}

## Teach Classmate

### Elevator 30s
{t.get('elevator_30s', '-')}

### Classroom 3min
{t.get('classroom_3min', '-')}

### Analogy
{t.get('analogy', '-')}

## Reproduction Guide

### Environment
{r.get('environment', '-')}

### Dataset
{r.get('dataset', '-')}

### Commands
{bullets(r.get('commands', []))}

### Common Errors
{bullets(r.get('common_errors', []))}

## Change Log
{bullets(report.get('change_log', []))}
""".strip()
