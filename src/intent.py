import re

# Cheap heuristic, not an LLM call -- misses and occasional false positives
# are expected and accepted. The explicit `compare` field on AskRequest
# (src/api.py) is the intended override when this misses or the caller
# wants precise control.
_COMPARISON_PATTERNS = [
    r"\bcompar(e|ed|ison|ing)\b",
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\btrend(s)?\b",
    r"\bover time\b",
    r"\bacross (years|fiscal years|all years)\b",
    r"\byear[- ]over[- ]year\b",
    r"\byoy\b",
    r"\bchange(d)? (between|across|from)\b",
    r"\bevery year\b",
    r"\beach year\b",
    r"\ball years\b",
]
_COMPARISON_RE = re.compile("|".join(_COMPARISON_PATTERNS), re.IGNORECASE)


def detect_comparison_intent(query: str) -> bool:
    return bool(_COMPARISON_RE.search(query))
