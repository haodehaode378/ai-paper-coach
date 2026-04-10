import re
from typing import Iterable


SECTION_RE = re.compile(
    r"\n(?P<header>(?:\d+(?:\.\d+)*\s+)?(?:[A-Z][A-Za-z0-9\-]{1,30})(?:[ \t]+[A-Za-z0-9\-\(\)\/:]{1,30}){0,8})\n"
)

PRIORITY_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("abstract", 130),
    ("introduction", 120),
    ("related work", 95),
    ("background", 85),
    ("method", 120),
    ("approach", 110),
    ("model", 100),
    ("architecture", 95),
    ("experiment", 120),
    ("evaluation", 110),
    ("result", 105),
    ("ablation", 100),
    ("discussion", 80),
    ("conclusion", 105),
)

# Hard-preserve core sections when present.
CORE_SECTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("abstract", ("abstract",)),
    ("introduction", ("introduction", "intro")),
    ("method", ("method", "approach", "architecture", "framework")),
    ("experiment", ("experiment", "evaluation", "results", "ablation")),
    ("conclusion", ("conclusion", "discussion", "future work")),
)


def _normalize_body(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _balanced_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars < 200:
        return text[:max_chars]

    head_len = int(max_chars * 0.72)
    tail_len = max_chars - head_len - len("\n...\n")
    if tail_len < 40:
        return text[:max_chars]
    return f"{text[:head_len]}\n...\n{text[-tail_len:]}"


def split_sections(text: str) -> dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        return {"EMPTY": ""}

    matches = list(SECTION_RE.finditer(raw))
    if not matches:
        return {"FULL_TEXT": _normalize_body(raw)}

    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        header = " ".join(match.group("header").split())
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        body = _normalize_body(raw[start:end])
        if body:
            sections[header[:80]] = body

    if not sections:
        sections["FULL_TEXT"] = _normalize_body(raw)
    return sections


def _section_score(title: str, content: str) -> int:
    title_l = title.lower()
    score = min(len(content) // 80, 70)
    for kw, bonus in PRIORITY_KEYWORDS:
        if kw in title_l:
            score += bonus
    return score


def _core_slot(title: str) -> str | None:
    lower = title.lower()
    for slot, keys in CORE_SECTION_RULES:
        if any(k in lower for k in keys):
            return slot
    return None


def _dedupe_keep_order(items: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = (item["section"], item["content"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _fit_content_with_budget(content: str, remaining_budget: int, min_chars: int = 240) -> str | None:
    if remaining_budget <= 0:
        return None
    if len(content) <= remaining_budget:
        return content
    if remaining_budget < min_chars:
        return None
    return _balanced_truncate(content, remaining_budget)


def top_chunks(
    sections: dict[str, str],
    max_sections: int = 5,
    max_chars_each: int = 1400,
    max_total_chars: int = 5200,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str | int | None]] = []
    for title, body in sections.items():
        normalized = _normalize_body(body)
        if not normalized:
            continue
        chunk = _balanced_truncate(normalized, max_chars_each)
        candidates.append(
            {
                "section": title,
                "content": chunk,
                "score": _section_score(title, normalized),
                "raw_len": len(normalized),
                "core_slot": _core_slot(title),
            }
        )

    if not candidates:
        return [{"section": "FULL_TEXT", "content": ""}]

    candidates.sort(key=lambda x: (int(x["score"]), int(x["raw_len"])), reverse=True)

    selected: list[dict[str, str]] = []
    selected_sections: set[str] = set()
    total_chars = 0

    # Pass 1: hard-preserve one section for each core slot when present.
    for slot, _keys in CORE_SECTION_RULES:
        if len(selected) >= max_sections:
            break
        slot_candidates = [c for c in candidates if c.get("core_slot") == slot]
        if not slot_candidates:
            continue
        best = slot_candidates[0]
        section = str(best["section"])
        if section in selected_sections:
            continue
        remaining = max_total_chars - total_chars
        fitted = _fit_content_with_budget(str(best["content"]), remaining)
        if not fitted:
            continue
        selected.append({"section": section, "content": fitted})
        selected_sections.add(section)
        total_chars += len(fitted)

    # Pass 2: fill remaining slots by priority while respecting total budget.
    for item in candidates:
        if len(selected) >= max_sections:
            break
        section = str(item["section"])
        if section in selected_sections:
            continue
        remaining = max_total_chars - total_chars
        if remaining <= 0:
            break
        fitted = _fit_content_with_budget(str(item["content"]), remaining, min_chars=320)
        if not fitted:
            continue
        selected.append({"section": section, "content": fitted})
        selected_sections.add(section)
        total_chars += len(fitted)

    if not selected:
        first = candidates[0]
        fallback = _balanced_truncate(str(first["content"]), max_total_chars)
        selected = [{"section": str(first["section"]), "content": fallback}]

    return _dedupe_keep_order(selected)
