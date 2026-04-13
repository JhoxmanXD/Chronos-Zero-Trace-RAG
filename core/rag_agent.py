"""Core RAG agent orchestration and iterative research flow."""

from __future__ import annotations

from typing import Any

import random
import threading

from core.zero_trace_rag import PrivacyError, SearchResult, ZeroTraceRAG, search_brave_api

WEB_AGENT_SYSTEM_PROMPT = (
    "You are an OSINT specialist. Analyze the user request and produce a SINGLE technical search query in ENGLISH. "
    "Strict rules: 1) Always translate intent into English. "
    "2) If the user asks to download files, comics, or books, use dorks such as filetype:cbz, filetype:pdf, inurl:mega. "
    "3) Exclude SEO noise using -news -review -ign -blog. "
    "4) Keep proper nouns unchanged. "
    "CRITICAL: Search engines block complex dorks. Never use parentheses or multiple OR/AND chains. "
    "If multiple concepts are needed, split into at most 2 simple queries separated by ||. "
    "5) Never include source code blocks, raw logs, IPs, or private data in the query. "
    "Return ONLY the search string with operators. No explanations, no quotes, no natural-language preface."
)

EVALUATOR_SYSTEM_PROMPT = (
    "You are a technical context evaluator for iterative RAG. "
    "You will receive the original question and the current web context. "
    "Respond ONLY with one exact format: "
    "1) SUFFICIENT "
    "2) NEW_SEARCH: <technical query in English with useful operators>. "
    "Rules: no explanations, no markdown, no source code, no private data. "
    "If key evidence is missing, return NEW_SEARCH."
)

DIRECT_SYSTEM_PROMPT = (
    "You are a precise and honest technical assistant. "
    "If evidence is missing, state it clearly. "
    "Do not invent sources or unverifiable claims."
)

THINKING_SYSTEM_PROMPT = (
    "Strict rule: use exactly one <think>...</think> block and never place nested think tags inside it. "
    "Then provide the final answer outside the block. "
    "When responding to the user, use the same language the user used."
)

def run_research_with_runtime(runtime: dict[str, Any], **kwargs):
    """Run iterative research using runtime-injected dependencies from the app layer."""
    globals().update(runtime)
    return run_iterative_research(**kwargs)

def search_duckduckgo_tor(query: str, rag: ZeroTraceRAG, top_k: int = 5) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        return []

    resp = rag._safe_external_get(
        "https://html.duckduckgo.com/html/",
        params={"q": sanitized_query, "kl": "wt-wt"},
        timeout=(8, 25),
        expected_hosts=["html.duckduckgo.com"],
    )
    resp.raise_for_status()
    html_text = resp.text

    link_matches = list(
        re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    snippet_matches = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    results: list[SearchResult] = []
    pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
    seen_urls = set()
    for idx, match in enumerate(link_matches):
        raw_url = parse_duckduckgo_redirect(match.group(1).strip())
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            continue
        if ZeroTraceRAG._is_blocked_host(host):
            continue

        clean_url = ZeroTraceRAG._strip_tracking_params(raw_url)
        if not clean_url or clean_url in seen_urls:
            continue

        title = strip_html(match.group(2))[:220]
        snippet = strip_html(snippet_matches[idx] if idx < len(snippet_matches) else "")[:600]
        if not title:
            continue

        seen_urls.add(clean_url)
        results.append(SearchResult(title=title, url=clean_url, snippet=snippet))
        if len(results) >= pool_limit:
            break

    return diversify_results(results, top_k)


def search_wikipedia_tor(query: str, rag: ZeroTraceRAG, top_k: int = 5) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        return []

    pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
    resp = rag._safe_external_get(
        "https://es.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "format": "json",
            "utf8": 1,
            "srlimit": min(pool_limit, 20),
            "srsearch": sanitized_query,
        },
        timeout=(8, 25),
        expected_hosts=["es.wikipedia.org"],
    )
    resp.raise_for_status()
    payload = resp.json()

    results: list[SearchResult] = []
    for item in (payload.get("query", {}) or {}).get("search", []):
        title = " ".join(str(item.get("title", "")).split())[:220]
        pageid = item.get("pageid")
        snippet = strip_html(str(item.get("snippet", "")))[:600]
        if not title or not pageid:
            continue
        url = f"https://es.wikipedia.org/?curid={pageid}"
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= pool_limit:
            break

    return diversify_results(results, top_k)


def search_web_tor_with_fallback(
    query: str,
    rag: ZeroTraceRAG,
    top_k: int = 5,
    preferred_engine: str = "auto",
    logger=None,
) -> list[SearchResult]:
    log = logger or (lambda _msg: None)

    def _search_searxng_prioritized() -> list[SearchResult]:
        # In Tor mode, prioritize onion services for better stability and operational anonymity.
        sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
        if len(sanitized_query) < 3:
            return []

        params = {
            "q": sanitized_query,
            "format": "json",
            "language": "en-US",
            "safesearch": 0,
        }

        configured_instances = list(getattr(rag, "searx_instances", []) or [])
        onion_instances = [
            base_url
            for base_url in configured_instances
            if (urlparse(base_url).hostname or "").lower().endswith(".onion")
        ]
        clearnet_instances = [base_url for base_url in configured_instances if base_url not in onion_instances]
        ordered_instances = [
            *random.sample(onion_instances, k=len(onion_instances)),
            *random.sample(clearnet_instances, k=len(clearnet_instances)),
        ]
        max_attempts = get_max_instance_attempts()
        if len(ordered_instances) > max_attempts:
            log(
                "SearXNG limited for latency control: "
                f"{max_attempts}/{len(ordered_instances)} instance(s) in this attempt."
            )
            ordered_instances = ordered_instances[:max_attempts]

        if onion_instances:
            log(f"SearXNG onion prioritized: {len(onion_instances)} onion instance(s) first.")

        failures: list[str] = []
        for base_url in ordered_instances:
            endpoint = f"{base_url}/search"
            try:
                payload = rag._searx_request(endpoint, params)
                results = rag._extract_results(payload, top_k)
                if results:
                    return results
                failures.append(f"{base_url}: no useful results")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{base_url}: {exc}")

        if failures:
            raise RuntimeError("SearXNG returned no useful results. Details: " + " | ".join(failures))
        return []

    if preferred_engine == "wikipedia_only":
        engines = [
            (
                "wikipedia_only",
                "Wikipedia",
                lambda: search_wikipedia_tor(query, rag, top_k=top_k),
            )
        ]
    elif preferred_engine == "duckduckgo":
        engines = [
            (
                "duckduckgo",
                "DuckDuckGo HTML",
                lambda: search_duckduckgo_tor(query, rag, top_k=top_k),
            ),
            (
                "searxng",
                "SearXNG",
                _search_searxng_prioritized,
            ),
        ]
    else:
        engines = [
            (
                "searxng",
                "SearXNG",
                _search_searxng_prioritized,
            ),
            (
                "duckduckgo",
                "DuckDuckGo HTML",
                lambda: search_duckduckgo_tor(query, rag, top_k=top_k),
            ),
        ]

    failures: list[str] = []

    for _, engine_label, engine_fn in engines:
        log(f"Intentando motor web: {engine_label}")
        try:
            results = engine_fn()
            if results:
                log(f"Motor web exitoso: {engine_label} ({len(results)} resultado(s)).")
                return results
            failures.append(f"{engine_label} no useful results")
            log(f"Engine returned no results: {engine_label}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{engine_label}: {exc}")
            log(f"Engine failed: {engine_label} -> {exc}")

    raise RuntimeError("Could not retrieve anonymous web context. Details: " + " | ".join(failures))


def extract_web_query(
    user_text: str,
    chat_history: list[dict],
    lm_url: str,
    model_name: str,
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> list[str]:
    # Keep a short rolling context to preserve semantic continuity for web queries.
    recent_messages: list[str] = []
    for item in reversed(chat_history or []):
        role = str(item.get("role", "")).strip().lower()
        if role == "system":
            continue

        content = " ".join(str(item.get("content", "")).split())
        if not content:
            continue

        label = "User" if role == "user" else "Assistant"
        recent_messages.append(f"{label}: {content[:1000]}")
        if len(recent_messages) >= 6:
            break

    recent_messages.reverse()
    recent_context = "\n".join(recent_messages) if recent_messages else "No recent context."
    web_agent_input = f"Recent context: {recent_context}\n\nNew request: {user_text}"

    client = get_llm_client(
        lm_url=lm_url,
        active_provider=active_provider,
        provider_settings=provider_settings,
    )
    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.0,
            # Short token cap keeps the web-query agent fast.
            max_tokens=60,
            timeout=12.0,
            messages=[
                {"role": "system", "content": WEB_AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": web_agent_input},
            ],
        )
        extracted = (response.choices[0].message.content or "").strip()
        return split_and_sanitize_queries(extracted, user_text, max_queries=2)
    finally:
        try:
            client.close()
        except Exception:
            pass


def append_unique_sources(accumulated: list[SearchResult], incoming: list[SearchResult]) -> int:
    seen_urls = {item.url for item in accumulated}
    added = 0
    for item in incoming:
        if item.url in seen_urls:
            continue
        accumulated.append(item)
        seen_urls.add(item.url)
        added += 1
    return added


def build_evaluator_context(sources: list[SearchResult], max_items: int | None = None) -> str:
    if not sources:
        return "No web context available."

    if max_items is None:
        max_items = int(globals().get("EVALUATOR_MAX_CONTEXT_SOURCES", 10))

    lines: list[str] = []
    for idx, item in enumerate(sources[:max_items], start=1):
        lines.append(
            f"[{idx}] Title: {item.title[:140]}\n"
            f"URL: {item.url}\n"
            f"Snippet: {item.snippet[:320]}"
        )
    return "\n\n".join(lines)


def evaluate_research_context(
    user_question: str,
    sources: list[SearchResult],
    lm_url: str,
    model_name: str,
    *,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
) -> tuple[str, str | None]:
    context_text = build_evaluator_context(sources)

    client = get_llm_client(
        lm_url=lm_url,
        active_provider=active_provider,
        provider_settings=provider_settings,
    )
    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.0,
            max_tokens=50,
            timeout=12.0,
            messages=[
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Original question:\n"
                        f"{user_question}\n\n"
                        "Current web context:\n"
                        f"{context_text}"
                    ),
                },
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
    finally:
        try:
            client.close()
        except Exception:
            pass

    normalized = " ".join(raw.split())
    upper = normalized.upper()
    if upper.startswith("SUFFICIENT"):
        return "SUFFICIENT", None

    marker = "NEW_SEARCH:"
    if upper.startswith(marker):
        new_query_raw = normalized.split(":", 1)[1].strip() if ":" in normalized else ""
        sanitized_query = sanitize_query_for_antibot(new_query_raw)
        if len(sanitized_query) >= 3:
            return "NEW_SEARCH", sanitized_query

    return "SUFFICIENT", None


def interruptible_sleep(seconds: float, stop_event: threading.Event | None) -> None:
    if stop_event is None:
        time.sleep(max(0.0, seconds))
        return

    remaining = max(0.0, seconds)
    slice_seconds = 0.12
    while remaining > 0 and not stop_event.is_set():
        current_slice = min(slice_seconds, remaining)
        time.sleep(current_slice)
        remaining -= current_slice


def run_iterative_research(
    *,
    user_text: str,
    chat_history: list[dict],
    lm_url: str,
    model_name: str,
    web_mode: str,
    tor_proxy: str,
    searx_instances: list[str],
    tor_web_engine_preference: str,
    context_limit_tokens: int,
    logger,
    active_provider: str | None = None,
    provider_settings: dict | None = None,
    stop_event: threading.Event | None = None,
    on_tor_status=None,
    use_cache: bool = False,
) -> tuple[list[SearchResult], list[dict], bool]:
    log = logger or (lambda _msg: None)
    used_cache = False
    aggregated_sources: list[SearchResult] = []

    if web_mode != "brave" and not searx_instances:
        raise PrivacyError("No SearXNG instances configured. Add at least one valid HTTPS URL.")

    search_queries = extract_web_query(
        user_text,
        chat_history=chat_history,
        lm_url=lm_url,
        model_name=model_name,
        active_provider=active_provider,
        provider_settings=provider_settings,
    )
    summarized_queries = " | ".join(search_queries)
    log(
        "Initial web-agent query(ies): "
        f"{len(search_queries)} -> {summarized_queries}"
    )

    rag: ZeroTraceRAG | None = None
    try:
        if web_mode == "tor":
            rag = create_rag(
                lm_url=lm_url,
                model_name=model_name,
                tor_proxy=tor_proxy,
                searx_instances=searx_instances,
                active_provider=active_provider,
                provider_settings=provider_settings,
            )
            log("Verifying Tor egress...")
            run_coro(rag.verify_tor())
            if on_tor_status:
                on_tor_status("ok", "Tor connection verified during this request.")

        for iteration in range(1, RESEARCH_MAX_ITERATIONS + 1):
            if stop_event is not None and stop_event.is_set():
                break

            log(f"[Research] Iteration {iteration}/{RESEARCH_MAX_ITERATIONS}.")
            had_successful_query = False
            for query_idx, query_for_iteration in enumerate(search_queries, start=1):
                if stop_event is not None and stop_event.is_set():
                    break

                log(
                    "[Research] Running query "
                    f"{query_idx}/{len(search_queries)}: {query_for_iteration}"
                )
                iteration_results: list[SearchResult] = []

                cache_key = ""
                if use_cache:
                    cache_key = build_search_cache_key(
                        query=query_for_iteration,
                        web_mode=web_mode,
                        preferred_engine=(
                            tor_web_engine_preference
                            if web_mode == "tor"
                            else ("brave_api" if web_mode == "brave" else "searxng_direct")
                        ),
                        top_k=5,
                        searx_instances=([] if web_mode == "brave" else searx_instances),
                    )
                    cached_sources = get_cached_search_results(cache_key)
                    if cached_sources:
                        record_search_cache_event(hit=True)
                        used_cache = True
                        iteration_results = cached_sources
                        had_successful_query = True
                        log(
                            f"[Research] Cache HIT on iteration {iteration} "
                            f"({len(iteration_results)} result(s))."
                        )
                    else:
                        record_search_cache_event(hit=False)
                        log(f"[Research] Cache MISS on iteration {iteration}.")

                if not iteration_results:
                    try:
                        if web_mode == "brave":
                            brave_api_key = get_secret("brave_api_key")
                            if not brave_api_key:
                                raise ValueError("Brave API key is not configured.")
                            iteration_results = search_brave_api(
                                query_for_iteration,
                                brave_api_key,
                                top_k=5,
                            )
                        elif web_mode == "tor":
                            if rag is None:
                                raise RuntimeError("Tor RAG is not initialized.")
                            iteration_results = search_web_tor_with_fallback(
                                query_for_iteration,
                                rag,
                                top_k=5,
                                preferred_engine=tor_web_engine_preference,
                                logger=log,
                            )
                        else:
                            iteration_results = search_web_direct(
                                query_for_iteration,
                                searx_instances,
                                top_k=5,
                            )
                        had_successful_query = True
                    except Exception as search_exc:  # noqa: BLE001
                        log(f"[Research] Iteration {iteration} failed: {search_exc}")
                        continue

                    if use_cache and cache_key:
                        put_cached_search_results(cache_key, iteration_results)
                        log(
                            "[Research] Cache updated on iteration "
                            f"{iteration} with {len(iteration_results)} result(s)."
                        )

                added_count = append_unique_sources(aggregated_sources, iteration_results)
                log(
                    "[Research] Partial result "
                    f"iter={iteration} query={query_idx}: +{added_count}, total={len(aggregated_sources)}."
                )

                # Anti-bot pacing to avoid burst behavior that often triggers HTTP 403.
                sleep_seconds = random.uniform(1.5, 3.5)
                log(f"[Research] Anti-bot delay applied: {sleep_seconds:.2f}s")
                interruptible_sleep(sleep_seconds, stop_event)

            if not had_successful_query and not aggregated_sources:
                log("[Research] No query returned results in this iteration.")
                break

            if iteration >= RESEARCH_MAX_ITERATIONS:
                log("[Research] 3-iteration limit reached. Ending research phase.")
                break

            try:
                decision, next_query = evaluate_research_context(
                    user_question=user_text,
                    sources=aggregated_sources,
                    lm_url=lm_url,
                    model_name=model_name,
                    active_provider=active_provider,
                    provider_settings=provider_settings,
                )
            except Exception as eval_exc:  # noqa: BLE001
                log(f"[Research] Evaluator unavailable: {eval_exc}. Using current context.")
                break

            if decision == "SUFFICIENT":
                log("[Research] Evaluator: context is SUFFICIENT.")
                break

            if decision == "NEW_SEARCH" and next_query:
                search_queries = [next_query]
                log(f"[Research] Missing context. New search generated: {next_query}")
                continue

            log("[Research] Evaluator returned no valid action. Using current context.")
            break

        if aggregated_sources:
            llm_messages = build_rag_messages(
                user_question=user_text,
                web_results=aggregated_sources,
                history=chat_history,
                context_limit_tokens=context_limit_tokens,
            )
        else:
            llm_messages = build_direct_messages(chat_history, context_limit_tokens=context_limit_tokens)

        return aggregated_sources, llm_messages, used_cache
    finally:
        if rag is not None:
            close_rag_safely(rag)


