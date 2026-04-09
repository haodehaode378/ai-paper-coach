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


def _normalize_body(text: str) -> str:
    # Keep newlines to preserve paragraph boundaries; normalize intra-line spaces.
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


def top_chunks(
    sections: dict[str, str],
    max_sections: int = 6,
    max_chars_each: int = 1600,
    max_total_chars: int = 7200,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
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
            }
        )

    if not candidates:
        return [{"section": "FULL_TEXT", "content": ""}]

    # Priority first, then content length.
    candidates.sort(key=lambda x: (x["score"], x["raw_len"]), reverse=True)

    selected: list[dict[str, str]] = []
    total_chars = 0
    for item in candidates:
        if len(selected) >= max_sections:
            break
        next_len = len(item["content"])
        if selected and total_chars + next_len > max_total_chars:
            continue
        selected.append({"section": item["section"], "content": item["content"]})
        total_chars += next_len

    if not selected:
        first = candidates[0]
        selected = [{"section": first["section"], "content": first["content"][:max_total_chars]}]

    return _dedupe_keep_order(selected)
