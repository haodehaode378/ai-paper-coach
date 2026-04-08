import re


SECTION_RE = re.compile(r"\n(?P<header>(?:\d+\.?\d*\s+)?[A-Z][A-Za-z\-\s]{2,40})\n")


def split_sections(text: str) -> dict[str, str]:
    if not text.strip():
        return {"EMPTY": ""}

    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return {"FULL_TEXT": text}

    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        header = " ".join(match.group("header").split())
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections[header[:80]] = body

    if not sections:
        sections["FULL_TEXT"] = text
    return sections


def top_chunks(sections: dict[str, str], max_sections: int = 8, max_chars_each: int = 2200) -> list[dict[str, str]]:
    items = []
    for title, body in sections.items():
        items.append({"section": title, "content": body[:max_chars_each]})
    items.sort(key=lambda x: len(x["content"]), reverse=True)
    return items[:max_sections]
