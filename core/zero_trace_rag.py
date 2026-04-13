#!/usr/bin/env python3
"""
Zero-Trace RAG for local LLM usage with LM Studio + SearXNG + Tor.

Main features:
- Fail-closed web egress: never uses direct network outside Tor.
- Query sanitization to reduce personal-data leakage.
- SearXNG instance rotation with strict host validation.
- Local LM Studio streaming with robust error handling.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import random
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from requests import Response
from requests.adapters import HTTPAdapter
from requests.exceptions import ProxyError, RequestException, Timeout
from urllib3.util.retry import Retry


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}\b"
)
PHONE_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
URL_RE = re.compile(r"\bhttps?://\S+\b", flags=re.IGNORECASE)
TOR_BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0"
RETRY_JITTER_RANGE_SECONDS = (0.08, 0.32)
DEFAULT_SEARCH_INSTANCE_ATTEMPTS = 4
MAX_WEB_RESULTS_POOL_FACTOR = 3


class PrivacyError(RuntimeError):
    """Privacy exception used to stop execution in fail-closed mode."""


class ZeroTraceRAG:
    def __init__(
        self,
        lm_base_url: str,
        model_name: str,
        tor_proxy: str,
        searx_instances: Iterable[str],
        lm_api_key: str = "lm-studio",
    ) -> None:
        self.strict_local_llm = os.getenv("STRICT_LOCAL_LLM", "true").lower() != "false"
        self.lm_base_url = lm_base_url.rstrip("/")
        self.model_name = model_name
        self.tor_proxy = tor_proxy

        self._validate_tor_proxy(self.tor_proxy)
        self._validate_lm_url(self.lm_base_url, self.strict_local_llm)

        self.searx_instances = self._sanitize_instances(searx_instances)
        self.searx_hosts = {urlparse(url).hostname.lower() for url in self.searx_instances}

        self.client = AsyncOpenAI(base_url=self.lm_base_url, api_key=lm_api_key)
        self.session = self._build_hardened_session()

    def _build_hardened_session(self) -> requests.Session:
        session = requests.Session()

        # Avoid inheriting proxy environment variables that could bypass privacy controls.
        session.trust_env = False

        # SOCKS5h forces remote DNS via Tor and minimizes local DNS leak risk.
        session.proxies = {
            "http": self.tor_proxy,
            "https": self.tor_proxy,
        }

        # Add jitter so retry timing is less fingerprintable.
        retry_kwargs = {
            "total": 2,
            "connect": 2,
            "read": 2,
            "status": 1,
            "backoff_factor": 0.7,
            "status_forcelist": [429, 500, 502, 503, 504],
            "allowed_methods": frozenset({"GET"}),
            "raise_on_status": False,
            "respect_retry_after_header": True,
        }
        retry_jitter = random.uniform(*RETRY_JITTER_RANGE_SECONDS)
        try:
            retry = Retry(backoff_jitter=retry_jitter, **retry_kwargs)
        except TypeError:
            class _RetryWithJitter(Retry):
                def get_backoff_time(self) -> float:  # noqa: ANN001
                    base_delay = super().get_backoff_time()
                    if base_delay <= 0:
                        return 0.0
                    return base_delay + random.uniform(*RETRY_JITTER_RANGE_SECONDS)

            retry = _RetryWithJitter(**retry_kwargs)

        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update(
            {
                "User-Agent": TOR_BROWSER_USER_AGENT,
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "DNT": "1",
                "Sec-GPC": "1",
            }
        )
        return session

    @staticmethod
    def _sanitize_instances(instances: Iterable[str]) -> List[str]:
        clean = []
        for instance in instances:
            candidate = (instance or "").strip().rstrip("/")
            if not candidate:
                continue
            parsed = urlparse(candidate)
            host = (parsed.hostname or "").lower()
            is_onion = host.endswith(".onion")

            # Clearnet requires HTTPS; .onion allows HTTP because Tor provides transport encryption.
            allows_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and is_onion)
            if not allows_scheme or not host:
                continue
            if ZeroTraceRAG._is_blocked_host(host):
                continue
            clean.append(candidate)
        if not clean:
            raise ValueError("No valid SearXNG instances found (HTTPS clearnet or HTTP .onion).")
        return clean

    @staticmethod
    def _validate_tor_proxy(proxy_url: str) -> None:
        parsed = urlparse((proxy_url or "").strip())
        if parsed.scheme.lower() != "socks5h":
            raise PrivacyError("Tor proxy must use socks5h:// to avoid DNS leaks.")
        if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost"}:
            raise PrivacyError("Tor proxy must be local (127.0.0.1 or localhost).")
        if parsed.port is None:
            raise PrivacyError("Tor proxy must include an explicit port, for example 9050.")

    @staticmethod
    def _validate_lm_url(base_url: str, strict_local: bool) -> None:
        parsed = urlparse((base_url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("LM_STUDIO_BASE_URL must start with http:// or https://")
        if not parsed.hostname:
            raise ValueError("LM_STUDIO_BASE_URL is invalid: empty hostname.")
        if strict_local and parsed.hostname.lower() not in {"127.0.0.1", "localhost"}:
            raise PrivacyError(
                "STRICT_LOCAL_LLM is enabled: LM Studio must run on localhost/127.0.0.1."
            )

    @staticmethod
    def _is_blocked_host(hostname: str) -> bool:
        host = (hostname or "").strip().lower()
        if not host:
            return True
        # Onion services are not treated as local/private hosts and are explicitly allowed.
        if host.endswith(".onion"):
            return False
        if host in {"localhost", "0.0.0.0"}:
            return True
        if host.endswith(".local") or host.endswith(".internal") or host.endswith(".arpa"):
            return True

        try:
            ip_obj = ipaddress.ip_address(host)
        except ValueError:
            return False

        return any(
            [
                ip_obj.is_private,
                ip_obj.is_loopback,
                ip_obj.is_link_local,
                ip_obj.is_multicast,
                ip_obj.is_reserved,
                ip_obj.is_unspecified,
            ]
        )

    @staticmethod
    def _sanitize_web_query(query: str) -> Tuple[str, int]:
        sanitized = " ".join((query or "").split())[:350]
        redactions = 0

        for pattern, replacement in (
            (EMAIL_RE, "[REDACTED_EMAIL]"),
            (IPV4_RE, "[REDACTED_IP]"),
            (PHONE_RE, "[REDACTED_PHONE]"),
            (URL_RE, "[REDACTED_URL]"),
        ):
            sanitized, count = pattern.subn(replacement, sanitized)
            redactions += count

        sanitized = " ".join(sanitized.split())
        return sanitized, redactions

    @staticmethod
    def _get_max_instance_attempts() -> int:
        raw = os.getenv("SEARX_MAX_INSTANCE_ATTEMPTS", str(DEFAULT_SEARCH_INSTANCE_ATTEMPTS))
        try:
            value = int(raw)
        except ValueError:
            value = DEFAULT_SEARCH_INSTANCE_ATTEMPTS
        return max(1, min(value, 12))

    @staticmethod
    def _diversify_results(results: List[SearchResult], top_k: int) -> List[SearchResult]:
        if top_k <= 0 or not results:
            return []

        buckets: dict[str, List[SearchResult]] = {}
        for item in results:
            host = (urlparse(item.url).hostname or "").lower() or "unknown"
            buckets.setdefault(host, []).append(item)

        selected: List[SearchResult] = []
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

    def _safe_external_get(
        self,
        url: str,
        *,
        params: dict | None,
        timeout: Tuple[int, int],
        expected_hosts: Sequence[str],
    ) -> Response:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        is_onion = host.endswith(".onion")

        # Politica fail-closed: HTTPS para clearnet; HTTP solo permitido para destinos .onion.
        allows_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and is_onion)
        if not allows_scheme:
            raise PrivacyError(f"Connection rejected by privacy policy: invalid destination scheme ({url}).")
        if host not in {h.lower() for h in expected_hosts}:
            raise PrivacyError(f"Connection rejected by privacy policy: host not allowed ({host}).")
        if self._is_blocked_host(host):
            raise PrivacyError(f"Connection rejected by privacy policy: blocked host ({host}).")

        response: Response = self.session.get(
            url,
            params=params,
            timeout=timeout,
            allow_redirects=False,
        )

        if 300 <= response.status_code < 400:
            raise PrivacyError(f"Redirect blocked by privacy policy at {url}.")
        return response

    @staticmethod
    def _validate_tor_exit_ip(ip_text: str) -> None:
        try:
            ip_obj = ipaddress.ip_address((ip_text or "").strip())
        except ValueError as exc:
            raise PrivacyError("Could not validate Tor exit IP.") from exc

        if any(
            [
                ip_obj.is_private,
                ip_obj.is_loopback,
                ip_obj.is_link_local,
                ip_obj.is_unspecified,
            ]
        ):
            raise PrivacyError("Reported exit IP is not public; aborting for safety.")

    @staticmethod
    def _strip_tracking_params(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if ZeroTraceRAG._is_blocked_host(parsed.hostname):
            return ""

        blocked_prefixes = ("utm_", "fbclid", "gclid", "mc_", "ref")
        clean_qs = [
            (k, v)
            for (k, v) in parse_qsl(parsed.query, keep_blank_values=False)
            if not any(k.lower().startswith(prefix) for prefix in blocked_prefixes)
        ]

        sanitized = parsed._replace(query=urlencode(clean_qs, doseq=True), fragment="")
        return urlunparse(sanitized)

    async def verify_tor(self) -> None:
        """
        Verify that network egress is routed through Tor.
        Abort immediately on failure to avoid real-IP leakage.
        """

        def _check() -> None:
            resp = self._safe_external_get(
                "https://check.torproject.org/api/ip",
                params=None,
                timeout=(7, 25),
                expected_hosts=["check.torproject.org"],
            )
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("IsTor", False):
                raise PrivacyError(
                    "Network egress does not appear to use Tor (IsTor=false)."
                )
            self._validate_tor_exit_ip(str(payload.get("IP", "")))

        try:
            await asyncio.to_thread(_check)
        except (ProxyError, Timeout) as exc:
            raise PrivacyError(
                "Unable to connect to Tor proxy on 127.0.0.1:9050. "
                "Verify that Tor is running."
            ) from exc
        except PrivacyError:
            raise
        except RequestException as exc:
            raise PrivacyError(
                "Tor validation failed against check.torproject.org."
            ) from exc

    async def search_web(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """
        Search SearXNG through Tor using rotating instances.
        """
        sanitized_query, redactions = self._sanitize_web_query(query)
        if len(sanitized_query) < 3:
            raise PrivacyError(
                "Query became too short after privacy sanitization."
            )

        if redactions > 0:
            print(f"[Privacy] Redacted {redactions} potential sensitive value(s) in web query.")

        params = {
            "q": sanitized_query,
            "format": "json",
            "language": "en-US",
            "safesearch": 0,
        }
        failures: List[str] = []

        instances = random.sample(self.searx_instances, k=len(self.searx_instances))
        max_attempts = self._get_max_instance_attempts()
        if len(instances) > max_attempts:
            instances = instances[:max_attempts]

        for base_url in instances:
            endpoint = f"{base_url}/search"
            try:
                payload = await asyncio.to_thread(self._searx_request, endpoint, params)
                results = self._extract_results(payload, top_k)
                if results:
                    return results
                failures.append(f"{base_url}: response had no useful results")
            except RuntimeError as exc:
                failures.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{base_url}: error inesperado: {exc}")

        detail = " | ".join(failures) if failures else "sin detalles"
        raise RuntimeError(f"Could not query SearXNG. Details: {detail}")

    def _searx_request(self, endpoint: str, params: dict) -> dict:
        try:
            parsed = urlparse(endpoint)
            host = (parsed.hostname or "").lower()
            if host not in self.searx_hosts:
                raise PrivacyError(f"Unauthorized SearXNG host: {host}")

            resp = self._safe_external_get(
                endpoint,
                params=params,
                timeout=(8, 25),
                expected_hosts=[host],
            )

            if resp.status_code in {403, 429, 503}:
                raise RuntimeError(f"{endpoint}: HTTP rejection {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except PrivacyError:
            raise
        except (ProxyError, Timeout) as exc:
            raise RuntimeError(
                f"{endpoint}: timeout/proxy error over Tor ({type(exc).__name__})"
            ) from exc
        except RequestException as exc:
            raise RuntimeError(f"{endpoint}: network failure ({type(exc).__name__})") from exc
        except ValueError as exc:
            raise RuntimeError(f"{endpoint}: invalid JSON") from exc

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").split())

    def _extract_results(self, payload: dict, top_k: int) -> List[SearchResult]:
        raw_results = payload.get("results", [])
        clean: List[SearchResult] = []
        pool_limit = max(top_k, top_k * MAX_WEB_RESULTS_POOL_FACTOR)
        seen_urls = set()

        for item in raw_results:
            title = self._normalize_text(item.get("title", ""))[:220]
            url = self._strip_tracking_params(self._normalize_text(item.get("url", "")))
            snippet = self._normalize_text(item.get("content", ""))[:600]

            if not title or not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)
            clean.append(SearchResult(title=title, url=url, snippet=snippet))
            if len(clean) >= pool_limit:
                break

        return self._diversify_results(clean, top_k)

    def build_messages(self, user_question: str, web_results: List[SearchResult]) -> list:
        """
        Build the RAG super-prompt for final answering.
        """
        fuentes = []
        for idx, r in enumerate(web_results, start=1):
            fuentes.append(
                f"[{idx}] Title: {r.title}\n"
                f"URL: {r.url}\n"
                f"Snippet: {r.snippet or 'No snippet available.'}"
            )

        contexto_web = "\n\n".join(fuentes) if fuentes else "No web results available."

        system_prompt = (
            "You are a precise and honest technical assistant. "
            "Use web context as evidence, cite links using [n] format, "
            "and never fabricate sources. If data is missing, state it clearly. "
            "Never invent links or expose sensitive personal data."
        )

        user_prompt = (
            "Original user question:\n"
            f"{user_question}\n\n"
            "Context retrieved from the internet:\n"
            f"{contexto_web}\n\n"
            "Respond in the same language the user used, including summary, key points, and cited links."
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def generate_stream(self, messages: list) -> str:
        """
        Solicita respuesta al LLM local y muestra streaming de tokens en consola.
        """
        full_text = []
        max_tokens = int(os.getenv("LM_MAX_TOKENS", "1200"))

        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in stream:
                delta = ""
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_text.append(delta)
                    print(delta, end="", flush=True)

            print()
            return "".join(full_text).strip()
        except APITimeoutError as exc:
            raise RuntimeError("Timeout al conectar con LM Studio.") from exc
        except APIConnectionError as exc:
            raise RuntimeError(
                "No se pudo conectar con LM Studio en el base_url configurado."
            ) from exc
        except APIStatusError as exc:
            raise RuntimeError(f"LM Studio devolvio error HTTP: {exc.status_code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Error inesperado en streaming del LLM: {exc}") from exc

    async def close(self) -> None:
        self.session.close()
        await self.client.close()


def search_brave_api(query: str, api_key: str, top_k: int = 5) -> list[SearchResult]:
    sanitized_query, _ = ZeroTraceRAG._sanitize_web_query(query)
    if len(sanitized_query) < 3:
        return []

    token = str(api_key or "").strip()
    if not token:
        raise ValueError("API Key de Brave no configurada.")

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Subscription-Token": token,
    }
    params = {
        "q": sanitized_query,
        "count": min(max(1, top_k * 2), 20),
    }

    with requests.Session() as session:
        session.trust_env = False
        resp = session.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            timeout=(8, 25),
        )
    if resp.status_code in {401, 403}:
        raise RuntimeError("Brave Search API rechazo la API Key (401/403).")
    resp.raise_for_status()

    payload = resp.json()
    raw_results = ((payload.get("web") or {}).get("results") or [])

    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in raw_results:
        title = ZeroTraceRAG._normalize_text(str(item.get("title", "")))[:220]
        raw_url = ZeroTraceRAG._normalize_text(str(item.get("url", "")))
        snippet = ZeroTraceRAG._normalize_text(str(item.get("description", "")))[:600]

        clean_url = ZeroTraceRAG._strip_tracking_params(raw_url)
        host = (urlparse(clean_url).hostname or "").lower() if clean_url else ""

        if not title or not clean_url or not host:
            continue
        if ZeroTraceRAG._is_blocked_host(host):
            continue
        if clean_url in seen_urls:
            continue

        seen_urls.add(clean_url)
        results.append(SearchResult(title=title, url=clean_url, snippet=snippet))

    return ZeroTraceRAG._diversify_results(results, top_k)


async def run_once() -> int:
    # Environment-driven configuration for flexible deployment.
    lm_base_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    model_name = os.getenv("LM_STUDIO_MODEL", "gguf@q4_k_s")
    tor_proxy = os.getenv("TOR_SOCKS5", "socks5h://127.0.0.1:9050")

    searx_instances = [
        os.getenv("SEARX_INSTANCE_1", "https://searx.tiekoetter.com"),
        os.getenv("SEARX_INSTANCE_2", "https://search.inetol.net"),
        os.getenv("SEARX_INSTANCE_3", "https://priv.au"),
        os.getenv("SEARX_INSTANCE_4", "https://search.datenkrake.ch"),
        os.getenv("SEARX_INSTANCE_5", "https://search.ononoki.org"),
        os.getenv("SEARX_INSTANCE_6", "https://search.rhscz.eu"),
        os.getenv("SEARX_INSTANCE_7", "https://search.sapti.me"),
        os.getenv("SEARX_INSTANCE_8", "https://searx.be"),
        os.getenv("SEARX_INSTANCE_9", "https://searx.party"),
        os.getenv("SEARX_INSTANCE_10", "https://searx.ro"),
        os.getenv("SEARX_INSTANCE_11", "https://searx.tsmdt.de"),
    ]

    rag = ZeroTraceRAG(
        lm_base_url=lm_base_url,
        model_name=model_name,
        tor_proxy=tor_proxy,
        searx_instances=searx_instances,
        lm_api_key=os.getenv("LM_STUDIO_API_KEY", "lm-studio"),
    )

    try:
        print("[Init] Verifying Tor egress (fail-closed mode)...")
        await rag.verify_tor()
        print("[OK] Anonymous environment is ready. Ask your question. Commands: /exit")

        while True:
            question = input("\n> ").strip()
            if not question:
                continue
            if question.lower() in {"/exit", "exit", "salir", "quit"}:
                print("Closing secure session.")
                return 0

            print("[1/3] Re-validating Tor...")
            await rag.verify_tor()

            print("[2/3] Searching SearXNG through Tor...")
            web_results = await rag.search_web(question, top_k=5)

            print("\nResults used as context:")
            for idx, item in enumerate(web_results, start=1):
                print(f"- [{idx}] {item.title}")
                print(f"      {item.url}")

            print("\n[3/3] Generating local LLM response (streaming):\n")
            messages = rag.build_messages(question, web_results)
            await rag.generate_stream(messages)
    except (RuntimeError, PrivacyError) as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    finally:
        await rag.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_once()))
