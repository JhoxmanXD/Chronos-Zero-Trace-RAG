"""General helper functions: token estimation, sanitization, and ranking utilities."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from core.zero_trace_rag import SearchResult, ZeroTraceRAG

TOKEN_RE = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
LOGICAL_OPERATOR_RE = re.compile(r"\b(?:AND|OR)\b|&&|\|\|", flags=re.IGNORECASE)


def estimate_text_tokens(text: str) -> int:
    """Estimate token count using lightweight regex tokenization.

    Args:
        text: Input text.

    Returns:
        int: Estimated token count.
    """
    if not text:
        return 0
    return len(TOKEN_RE.findall(text))


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate token count for a list of chat messages.

    Args:
        messages: Message list with content fields.

    Returns:
        int: Estimated token count.
    """
    total = 2
    for msg in messages:
        total += 4
        total += estimate_text_tokens(str(msg.get("content", "")))
    return max(total, 0)


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text by estimated token budget.

    Args:
        text: Input text.
        max_tokens: Maximum token estimate allowed.

    Returns:
        str: Truncated text.
    """
    if max_tokens <= 0:
        return ""
    tokens = TOKEN_RE.findall(text or "")
    if len(tokens) <= max_tokens:
        return text
    return " ".join(tokens[:max_tokens])


def sanitize_query_for_antibot(query: str) -> str:
    """Sanitize web query text to avoid anti-bot trigger patterns.

    Args:
        query: Raw query string.

    Returns:
        str: Safe sanitized query.
    """
    base = " ".join(str(query or "").split())
    if not base:
        return ""

    # Simplify only when complex dork logic is detected.
    needs_simplify = bool(re.search(r"[()]", base) or len(LOGICAL_OPERATOR_RE.findall(base)) >= 1)
    working = base
    if needs_simplify:
        working = re.sub(r"[()]", " ", working)
        working = re.sub(r"&&|\|\|", " ", working)
        working = re.sub(r"\b(?:AND|OR)\b", " ", working, flags=re.IGNORECASE)

    sanitized, _ = ZeroTraceRAG._sanitize_web_query(working)
    cleaned = " ".join(sanitized.split()).strip()
    if not cleaned:
        return ""

    if re.search(r"[()]", cleaned) or LOGICAL_OPERATOR_RE.search(cleaned):
        return ""

    return cleaned


def split_and_sanitize_queries(raw_text: str, fallback_text: str, max_queries: int = 2) -> list[str]:
    """Split multi-query strings and sanitize each part.

    Args:
        raw_text: Candidate query text that may contain '||' separators.
        fallback_text: Fallback text when all parsed queries fail.
        max_queries: Maximum number of final queries.

    Returns:
        list[str]: Sanitized query list.
    """
    raw_queries = [part.strip() for part in str(raw_text or "").split("||") if part.strip()]
    sanitized_queries: list[str] = []

    for query in raw_queries:
        safe_query = sanitize_query_for_antibot(query)
        if safe_query:
            sanitized_queries.append(safe_query)

    if sanitized_queries:
        return sanitized_queries[:max_queries]

    fallback_safe = sanitize_query_for_antibot(fallback_text)
    if fallback_safe:
        return [fallback_safe]

    return ["general web search"]


def diversify_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    """Diversify ranked results by host to reduce domain concentration.

    Args:
        results: Candidate search results.
        top_k: Desired number of outputs.

    Returns:
        list[SearchResult]: Diversified top results.
    """
    if top_k <= 0 or not results:
        return []

    buckets: dict[str, list[SearchResult]] = {}
    for item in results:
        host = (urlparse(item.url).hostname or "").lower() or "unknown"
        buckets.setdefault(host, []).append(item)

    selected: list[SearchResult] = []
    while len(selected) < top_k:
        moved = False
        for host in list(buckets.keys()):
            if not buckets[host]:
                continue
            selected.append(buckets[host].pop(0))
            moved = True
            if len(selected) >= top_k:
                break
        if not moved:
            break

    return selected
