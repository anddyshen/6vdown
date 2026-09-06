"""Pinyin initial search helpers (pypinyin optional)."""
from __future__ import annotations

try:
    from pypinyin import lazy_pinyin
    _HAS_PINYIN = True
except Exception:  # pragma: no cover - pypinyin not installed
    _HAS_PINYIN = False
    lazy_pinyin = None

_LATIN_CACHE: dict = {}


def initials(text) -> str:
    """Return pinyin-initial letters of CJK chars only (digits/latin skipped)."""
    if text is None:
        return ""
    out = []
    for ch in str(text):
        if _HAS_PINYIN and '\u4e00' <= ch <= '\u9fff':
            py = lazy_pinyin(ch)[0]
            if py:
                out.append(py[0])
    return "".join(out)


def _is_subseq(query: str, text: str) -> bool:
    it = iter(text)
    return all(c in it for c in query)


def match(fields, query: str) -> bool:
    """True when any field matches.

    - Empty query matches everything.
    - A field containing the query text directly (numbers/latin/chinese all
      supported) matches.
    - A pure-ASCII query also matches when it is a contiguous substring of the
      CJK-only pinyin-initial letters of a field (e.g. dy for dian-ying).
    """
    q = (query or "").strip().lower()
    if not q:
        return True
    pure_ascii = q.isascii()
    for f in fields:
        s = str(f or "")
        low = s.lower()
        if q in low:
            return True
        if pure_ascii:
            ini = _LATIN_CACHE.get(low)
            if ini is None:
                ini = initials(low)
                _LATIN_CACHE[low] = ini
            if ini and q in ini:
                return True
    return False


def clear_cache() -> None:
    _LATIN_CACHE.clear()