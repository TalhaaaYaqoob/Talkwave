"""
Scrape text content from user-provided URLs to enrich CrewAI agent context
AND to seed a runtime KB so the voice agent can answer specific factual
questions about the business.

Design goals
------------
* **Deep crawl by default.** When a user pastes a homepage URL we don't
  just grab that one page — we follow internal links and pull the most
  valuable pages (About, Services, Pricing, Menu, FAQ, Contact, Hours,
  Locations, Products, Team). This is what lets the voice agent answer
  questions like "what are your weekend hours?" or "do you accept
  Delta Dental?" even when the homepage doesn't contain that info.

* **Fail-soft.** A failed fetch never blocks workflow generation; the
  caller just sees less context. Every failure is logged with enough
  detail to diagnose from deploy logs.

* **Browser-like requests.** A realistic UA + headers, otherwise many
  managed-hosting providers (Cloudflare, AWS WAF) serve a 403 or a
  bot-challenge HTML to anything that looks like a script.

* **Multi-source extraction.** ``<title>`` + ``<meta>`` (incl. OG/Twitter)
  + ``<main>``/``<article>`` blocks, with a full-body fallback for SPAs.
  We do **not** strip ``<nav>``, ``<header>``, ``<footer>`` because for
  small business sites those frequently carry the actual service names,
  hours, address, and contact info.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from loguru import logger


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
# How many seed URLs the caller can pass in. Each one triggers its own crawl.
MAX_SEED_LINKS = 5

# How many internal pages we'll discover and fetch PER seed URL on top of the
# seed itself. 15 covers the typical small-business taxonomy comfortably
# (About + Services + Pricing + Menu + Contact + Hours + 6-8 product/location
# pages) without exploding fetch time.
MAX_INTERNAL_LINKS_PER_SEED = 15

# Hard cap across all seeds combined, so a user dropping 5 huge sites can't
# spawn 80 concurrent fetches.
MAX_TOTAL_PAGES = 30

MAX_BODY_BYTES = 400_000        # ~400 KB per page (text kept after decode)
TIMEOUT_SECONDS = 20
MAX_TEXT_CHARS_PER_PAGE = 10_000
MIN_USEFUL_CHARS = 30

# Hard cap on bytes we read off the wire per response, enforced WHILE streaming
# so a decompression bomb / multi-GB body can never be fully buffered into
# memory. We stop reading once we cross this and decode whatever we have.
MAX_DOWNLOAD_BYTES = 5_000_000  # 5 MB raw, generous for any real web page

# Politeness + resilience knobs.
MAX_CONCURRENT_FETCHES = 5      # max simultaneous requests to a single host
MAX_FETCH_ATTEMPTS = 3          # initial try + 2 retries on transient failures
RETRY_BACKOFF_SECONDS = 1.5     # base for exponential backoff between retries
RETRYABLE_STATUS = {429, 502, 503, 504}

# Total cap for the combined corpus returned to the caller — large enough
# to capture a full business site (homepage + a dozen sub-pages), small
# enough that we don't dump megabytes into Postgres / Qdrant.
MAX_TOTAL_CHARS = 240_000


# Realistic browser headers. UA is the single biggest factor in whether
# anti-bot middleware lets the request through.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # IMPORTANT: only advertise encodings httpx can actually decode with the
    # stdlib (gzip / deflate). We deliberately do NOT request "br" (Brotli) or
    # "zstd" because those need extra packages (brotli / zstandard) that aren't
    # installed — if we advertise them, a server may reply Brotli-encoded and
    # httpx will hand back raw compressed bytes, which decode to null-byte
    # garbage (0x00) and then get rejected by Postgres on KB insert.
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Regexes (compiled once at import time, shared across concurrent fetches)
# ---------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_META_NAMED_RE = re.compile(
    r"""<meta\b[^>]*?\bname\s*=\s*['"](?P<name>[^'"]+)['"][^>]*?"""
    r"""\bcontent\s*=\s*['"](?P<content>[^'"]*)['"]""",
    re.IGNORECASE,
)
_META_PROP_RE = re.compile(
    r"""<meta\b[^>]*?\bproperty\s*=\s*['"](?P<prop>[^'"]+)['"][^>]*?"""
    r"""\bcontent\s*=\s*['"](?P<content>[^'"]*)['"]""",
    re.IGNORECASE,
)
_MAIN_BLOCK_RE = re.compile(
    r"<(?P<tag>main|article)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)
_LINK_RE = re.compile(
    r"""<a\b[^>]*?\bhref\s*=\s*['"](?P<href>[^'"#]+)['"][^>]*>(?P<text>.*?)</a>""",
    re.DOTALL | re.IGNORECASE,
)


# Keywords that score a URL as high-value for a business voice agent. A page
# whose path or anchor text contains any of these is what we want to grab.
_HIGH_VALUE_KEYWORDS = (
    "about", "service", "services", "what-we-do", "what_we_do",
    "pricing", "price", "rates", "plans", "membership",
    "menu", "food", "drink", "drinks",
    "product", "products", "shop", "store", "catalog",
    "faq", "faqs", "questions", "help",
    "contact", "location", "locations", "hours", "find-us", "find_us",
    "team", "staff", "doctors", "providers", "attorneys", "instructors",
    "insurance", "billing", "appointment", "appointments", "booking", "book",
    "patient", "patients", "treatment", "treatments", "procedure", "procedures",
    "specialties", "specialty", "expertise",
    "policies", "policy", "terms-of-service", "privacy",
    "amenities", "facilities", "rooms", "suites",
    "programs", "courses", "classes", "schedule",
)

# URL substrings that mean "skip" — usually noise for a voice agent KB.
_SKIP_SUBSTRINGS = (
    "/wp-admin", "/wp-login", "/login", "/signin", "/sign-in", "/signup",
    "/sign-up", "/register", "/cart", "/checkout", "/account", "/my-account",
    "/cdn-cgi/", "/feed/", "?replytocom=",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".mp4", ".mp3", ".wav", ".mov", ".avi",
    ".css", ".js", ".xml", ".rss",
)

# Domains we never crawl even if linked from the seed (social / external).
_SKIP_DOMAINS = {
    "facebook.com", "www.facebook.com", "instagram.com", "www.instagram.com",
    "twitter.com", "x.com", "www.x.com", "linkedin.com", "www.linkedin.com",
    "youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com",
    "pinterest.com", "www.pinterest.com", "yelp.com", "www.yelp.com",
    "tripadvisor.com", "www.tripadvisor.com",
    "maps.google.com", "google.com/maps",
}


# Control chars that must never reach the corpus / Postgres. We keep the
# common whitespace ones (\t \n \r) and strip everything else in the C0/C1
# ranges, plus the NUL byte that Postgres rejects outright for text columns.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Markers that indicate a bot-challenge / anti-DDoS interstitial rather than
# real page content. These pages can exceed MIN_USEFUL_CHARS yet contain
# nothing useful for the KB, so we drop them.
_INTERSTITIAL_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "/cdn-cgi/challenge-platform",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
    "ddos protection by",
    "please verify you are a human",
    "verifying you are human",
    "ray id:",
)

# Cookie / privacy consent wall markers. A real page often has a cookie banner,
# so we only treat these as junk when they DOMINATE a very short page.
_CONSENT_MARKERS = (
    "we value your privacy",
    "accept all cookies",
    "this website uses cookies",
    "manage your cookie",
)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------
def _ip_is_blocked(ip_str: str) -> bool:
    """True if an IP is loopback / private / link-local / reserved / multicast.

    Blocks the cloud metadata endpoint (169.254.169.254), localhost, RFC1918
    ranges, etc. so a user-supplied URL can't make us fetch internal services.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # not a parseable IP → be safe and block
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _url_is_safe(url: str) -> bool:
    """Resolve ``url``'s host and reject non-public targets (SSRF guard).

    Runs DNS resolution off the event loop. Every resolved address must be a
    public IP; if any resolves to a private/loopback/etc. range we refuse the
    fetch. This also defends against DNS-rebinding to a degree by checking the
    actual resolved addresses, not just the hostname string.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.warning(f"[LinkScraper] Refusing non-http(s) URL: {url}")
        return False
    host = parsed.hostname
    if not host:
        logger.warning(f"[LinkScraper] Refusing URL with no host: {url}")
        return False

    # Literal IP in the URL → check directly.
    try:
        ipaddress.ip_address(host)
        if _ip_is_blocked(host):
            logger.warning(f"[LinkScraper] Refusing private/loopback IP URL: {url}")
            return False
        return True
    except ValueError:
        pass  # hostname, resolve below

    try:
        loop = asyncio.get_event_loop()
        infos = await loop.getaddrinfo(host, None)
    except Exception as e:
        logger.warning(f"[LinkScraper] DNS resolution failed for {host}: {e}")
        return False

    resolved = {info[4][0] for info in infos}
    if not resolved:
        return False
    for ip_str in resolved:
        if _ip_is_blocked(ip_str):
            logger.warning(
                f"[LinkScraper] Refusing {url} — host {host} resolves to "
                f"non-public address {ip_str}"
            )
            return False
    return True


def _decode_body(raw: bytes, resp: httpx.Response) -> str:
    """Decode raw bytes to text using the best available charset.

    Order: declared charset (Content-Type header) → charset_normalizer
    sniffing (if installed) → utf-8 with replacement. This avoids mojibake on
    pages that serve Windows-1252 / Shift-JIS without a UTF-8 charset.
    """
    declared = resp.charset_encoding
    if declared:
        try:
            return raw.decode(declared, errors="replace")
        except (LookupError, TypeError):
            pass
    try:
        from charset_normalizer import from_bytes  # type: ignore

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return raw.decode("utf-8", errors="replace")


def _looks_like_interstitial(text: str) -> bool:
    """True when the page is a bot-challenge or a consent-only wall."""
    low = text.lower()
    if any(marker in low for marker in _INTERSTITIAL_MARKERS):
        return True
    # Consent walls only count as junk when they dominate a tiny page; real
    # pages with a cookie banner have plenty of other text.
    if len(text) < 600 and any(marker in low for marker in _CONSENT_MARKERS):
        return True
    return False


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def _sanitize_text(text: str) -> str:
    """Remove NUL bytes and other non-printable control characters.

    Postgres ``text``/``varchar`` columns reject ``0x00`` outright
    (``invalid byte sequence for encoding "UTF8": 0x00``), and undecoded
    compressed responses are full of them. Stripping here guarantees anything
    we return is safe to persist and safe to feed the LLM.
    """
    if not text:
        return ""
    return _CONTROL_CHARS_RE.sub("", text)


def _looks_like_binary(text: str, sample: int = 2000) -> bool:
    """Heuristic: True when ``text`` is mostly non-printable — i.e. an
    undecoded compressed/binary body that slipped past content-type checks
    (e.g. a Brotli/zstd response we couldn't decompress). Such content is
    useless to the LLM and toxic to Postgres, so callers discard it.
    """
    if not text:
        return False
    head = text[:sample]
    if not head:
        return False
    # NUL bytes are a dead giveaway of undecoded binary.
    if "\x00" in head:
        return True
    non_printable = sum(
        1 for ch in head if ord(ch) < 0x20 and ch not in "\t\n\r"
    )
    return (non_printable / len(head)) > 0.10


def _clean_tags(html_fragment: str) -> str:
    """Strip tags / scripts / styles / comments and collapse whitespace.

    Keeps ``<nav>`` / ``<header>`` / ``<footer>`` because small-business
    sites stash hours, addresses, and service names there.
    """
    text = _SCRIPT_RE.sub(" ", html_fragment)
    text = _STYLE_RE.sub(" ", text)
    text = _NOSCRIPT_RE.sub(" ", text)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _extract_text_from_html(body: str, url: str) -> str:
    """Pull useful text out of ``body`` — title, meta tags, then main body."""
    parts: List[str] = []

    title_match = _TITLE_RE.search(body)
    if title_match:
        title = html.unescape(title_match.group(1)).strip()
        if title:
            parts.append(f"Title: {title}")

    meta_summary: List[str] = []
    seen_meta_values: set = set()
    for m in _META_NAMED_RE.finditer(body):
        name = m.group("name").lower()
        content = html.unescape(m.group("content")).strip()
        if not content or content.lower() in seen_meta_values:
            continue
        if name in (
            "description", "keywords", "author",
            "twitter:title", "twitter:description",
        ):
            meta_summary.append(f"{name}: {content}")
            seen_meta_values.add(content.lower())
    for m in _META_PROP_RE.finditer(body):
        prop = m.group("prop").lower()
        content = html.unescape(m.group("content")).strip()
        if not content or content.lower() in seen_meta_values:
            continue
        if prop in ("og:title", "og:description", "og:site_name", "og:type"):
            meta_summary.append(f"{prop}: {content}")
            seen_meta_values.add(content.lower())
    if meta_summary:
        parts.append("Meta:\n" + "\n".join(meta_summary))

    main_match = _MAIN_BLOCK_RE.search(body)
    body_text = _clean_tags(main_match.group("body") if main_match else body)
    if body_text:
        parts.append(body_text)

    combined = _sanitize_text("\n\n".join(p for p in parts if p))
    if len(combined) > MAX_TEXT_CHARS_PER_PAGE:
        combined = combined[:MAX_TEXT_CHARS_PER_PAGE]

    logger.info(
        f"[LinkScraper] {url} extracted {len(combined)} chars "
        f"(title={'yes' if title_match else 'no'}, "
        f"meta_tags={len(meta_summary)}, "
        f"main_block={'yes' if main_match else 'no'})"
    )
    return combined


# ---------------------------------------------------------------------------
# Link discovery
# ---------------------------------------------------------------------------
def _same_registrable_domain(host_a: str, host_b: str) -> bool:
    """Cheap eTLD+1 comparison good enough for our needs."""
    a = host_a.lower().lstrip(".")
    b = host_b.lower().lstrip(".")
    if a == b:
        return True
    # accept www / m / subdomain variations of the same root
    a_parts = a.split(".")
    b_parts = b.split(".")
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        return a_parts[-2:] == b_parts[-2:]
    return False


def _score_link(url: str, anchor_text: str) -> int:
    """Higher score = more likely to be useful for a voice agent KB."""
    path = urlparse(url).path.lower()
    text = anchor_text.lower()
    haystack = f"{path} {text}"
    score = 0
    for kw in _HIGH_VALUE_KEYWORDS:
        if kw in haystack:
            score += 5
    # Short, clean paths (top-level pages) are more likely to be useful
    segs = [s for s in path.split("/") if s]
    if 1 <= len(segs) <= 2:
        score += 2
    # Penalise long query-string / pagination URLs
    if "?" in url and "page=" in url:
        score -= 3
    if "page/" in path or "/tag/" in path or "/category/" in path:
        score -= 4
    return score


def _is_crawlable(url: str, root_host: str) -> bool:
    """True iff we should fetch this URL during deep-crawl."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    if parsed.netloc.lower() in _SKIP_DOMAINS:
        return False
    if not _same_registrable_domain(parsed.netloc, root_host):
        return False
    lower = url.lower()
    if any(skip in lower for skip in _SKIP_SUBSTRINGS):
        return False
    return True


def _discover_internal_links(
    body: str,
    base_url: str,
    limit: int,
) -> List[str]:
    """Parse `<a href>` tags from ``body``, rank them, return top ``limit``.

    The result excludes ``base_url`` itself and any URL we've already chosen
    to crawl.
    """
    root_host = urlparse(base_url).netloc
    scored: List[Tuple[int, str]] = []
    seen_norm: set = set()

    base_norm, _ = urldefrag(base_url)

    for m in _LINK_RE.finditer(body):
        href = m.group("href").strip()
        anchor = _clean_tags(m.group("text"))
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)
        if absolute == base_norm:
            continue
        if absolute in seen_norm:
            continue
        if not _is_crawlable(absolute, root_host):
            continue

        score = _score_link(absolute, anchor)
        if score <= 0:
            # Still keep some neutral links — they might be useful — but
            # only if we have headroom. Use a small floor so we don't
            # crawl pure noise.
            score = 1

        seen_norm.add(absolute)
        scored.append((score, absolute))

    # Highest score first, then alphabetical for stability
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = [url for _, url in scored[:limit]]
    logger.info(
        f"[LinkScraper] Discovered {len(scored)} internal link(s) under "
        f"{root_host}, crawling top {len(chosen)}: {chosen}"
    )
    return chosen


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
async def _stream_capped_body(resp: httpx.Response) -> bytes:
    """Read a response body but stop after ``MAX_DOWNLOAD_BYTES``.

    Reads the DECODED (decompressed) stream so a decompression bomb can't
    inflate past the cap — once we cross it we stop and use what we have.
    """
    chunks: List[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_DOWNLOAD_BYTES:
            logger.warning(
                f"[LinkScraper] {resp.url} exceeded {MAX_DOWNLOAD_BYTES} bytes — "
                f"truncating download"
            )
            break
    return b"".join(chunks)[:MAX_DOWNLOAD_BYTES]


async def _fetch_raw(
    client: httpx.AsyncClient,
    url: str,
    sem: asyncio.Semaphore,
) -> Optional[Tuple[str, str]]:
    """Return ``(html_body, final_url)`` or ``None`` on any failure.

    Hardened against: SSRF (private-IP targets), oversized / decompression-bomb
    bodies (streamed with a hard cap), charset mojibake (best-effort decode),
    and transient failures (retry with backoff on 429/5xx/timeout). Concurrency
    to a single host is bounded by ``sem``.
    """
    if not await _url_is_safe(url):
        return None

    last_reason = "unknown"
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            async with sem:
                async with client.stream(
                    "GET", url, follow_redirects=True, timeout=TIMEOUT_SECONDS
                ) as resp:
                    content_type = resp.headers.get("content-type", "").lower()

                    if resp.status_code in RETRYABLE_STATUS:
                        last_reason = f"HTTP {resp.status_code}"
                        # fall through to backoff/retry below
                    elif resp.status_code != 200:
                        logger.warning(
                            f"[LinkScraper] {url} returned non-200 status "
                            f"{resp.status_code}"
                        )
                        return None
                    else:
                        if content_type and not any(
                            marker in content_type
                            for marker in (
                                "text/html", "text/plain",
                                "application/xhtml", "application/xml",
                            )
                        ):
                            logger.info(
                                f"[LinkScraper] Skipping non-text content at "
                                f"{url} ({content_type})"
                            )
                            return None

                        raw = await _stream_capped_body(resp)
                        logger.info(
                            f"[LinkScraper] {url} → HTTP 200, "
                            f"content-type={content_type or '<none>'}, "
                            f"body={len(raw)} bytes"
                        )
                        body = _decode_body(raw, resp)[:MAX_BODY_BYTES]

                        # Guard against undecoded compressed bodies (a Brotli/
                        # zstd response we can't decompress). These look like
                        # text but are binary garbage full of NUL bytes.
                        if _looks_like_binary(body):
                            enc = resp.headers.get("content-encoding", "<none>")
                            logger.warning(
                                f"[LinkScraper] {url} returned undecodable/binary "
                                f"body (content-encoding={enc}) — discarding."
                            )
                            return None

                        return body, str(resp.url)
        except httpx.TimeoutException:
            last_reason = f"timeout after {TIMEOUT_SECONDS}s"
        except httpx.RequestError as e:
            last_reason = f"{type(e).__name__}: {e}"
        except Exception as e:
            logger.warning(
                f"[LinkScraper] Unexpected error fetching {url}: "
                f"{type(e).__name__}: {e}"
            )
            return None

        # Reached only on a retryable status or a transient transport error.
        if attempt < MAX_FETCH_ATTEMPTS:
            backoff = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.info(
                f"[LinkScraper] {url} attempt {attempt}/{MAX_FETCH_ATTEMPTS} "
                f"failed ({last_reason}) — retrying in {backoff:.1f}s"
            )
            await asyncio.sleep(backoff)

    logger.warning(
        f"[LinkScraper] {url} gave up after {MAX_FETCH_ATTEMPTS} attempts "
        f"({last_reason})"
    )
    return None


async def _fetch_and_extract(
    client: httpx.AsyncClient,
    url: str,
    sem: asyncio.Semaphore,
) -> Optional[Tuple[str, str]]:
    """Fetch + extract page text. Returns ``(text, final_url)`` or ``None``."""
    raw = await _fetch_raw(client, url, sem)
    if not raw:
        return None
    body, final_url = raw

    if "<" not in body[:200] and not body.lstrip().startswith("<"):
        text = _sanitize_text(body[:MAX_TEXT_CHARS_PER_PAGE])
    else:
        text = _extract_text_from_html(body, final_url)

    if _looks_like_interstitial(text):
        logger.warning(
            f"[LinkScraper] {final_url} looks like a bot-challenge / consent "
            f"interstitial — discarding (no real content)."
        )
        return None

    if len(text.strip()) < MIN_USEFUL_CHARS:
        logger.warning(
            f"[LinkScraper] {final_url} produced {len(text.strip())} chars "
            f"(min {MIN_USEFUL_CHARS}) — likely JS-rendered or behind bot challenge."
        )
        return None
    return text, final_url


# ---------------------------------------------------------------------------
# Deep crawl
# ---------------------------------------------------------------------------
async def _crawl_seed(
    client: httpx.AsyncClient,
    seed_url: str,
    *,
    remaining_budget: int,
    sem: asyncio.Semaphore,
) -> List[Tuple[str, str]]:
    """Fetch ``seed_url``, then up to ``MAX_INTERNAL_LINKS_PER_SEED`` of its
    internal links. Returns a list of ``(url, text)`` pairs.

    ``remaining_budget`` caps how many pages this seed can fetch in total
    (seed + internal links) so multi-seed inputs share a global limit.
    """
    if remaining_budget <= 0:
        return []

    # Fetch the seed first so we have its HTML for link discovery.
    raw_seed = await _fetch_raw(client, seed_url, sem)
    if not raw_seed:
        return []
    seed_body, seed_final_url = raw_seed

    seed_text = _extract_text_from_html(seed_body, seed_final_url)
    results: List[Tuple[str, str]] = []
    if len(seed_text.strip()) >= MIN_USEFUL_CHARS:
        results.append((seed_final_url, seed_text))
        remaining_budget -= 1

    if remaining_budget <= 0:
        return results

    internal_limit = min(MAX_INTERNAL_LINKS_PER_SEED, remaining_budget)
    internal_links = _discover_internal_links(
        seed_body, seed_final_url, limit=internal_limit,
    )

    if not internal_links:
        return results

    # Fetch all internal links concurrently (bounded by the shared semaphore)
    tasks = [_fetch_and_extract(client, link, sem) for link in internal_links]
    page_results = await asyncio.gather(*tasks)
    for pr in page_results:
        if pr is not None:
            results.append(pr)

    return results


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
def _dedupe_pages(pages: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Drop pages whose body text is a duplicate of one we already have."""
    seen: set = set()
    out: List[Tuple[str, str]] = []
    for url, text in pages:
        # Use a coarse content fingerprint so near-duplicate templated pages
        # don't both make it into the corpus.
        fingerprint = re.sub(r"\W+", "", text)[:2000]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append((url, text))
    return out


async def scrape_links(urls: List[str]) -> str:
    """Fetch ``urls`` AND their high-value internal pages, return combined text.

    For each URL the user provided we:
      1. Fetch the URL itself.
      2. Parse internal links from its HTML.
      3. Score & rank those links (services, pricing, about, contact, etc.).
      4. Fetch the top ``MAX_INTERNAL_LINKS_PER_SEED`` of them.
      5. Combine into one big context string.

    Total output is capped at ``MAX_TOTAL_CHARS`` so we never explode the
    KB / vector store.
    """
    if not urls:
        return ""

    # Normalize seeds: trim whitespace, prepend https:// when the user pasted a
    # bare host ("northitalia.com") so urlparse/httpx don't choke on it.
    seed_urls: List[str] = []
    for u in urls[:MAX_SEED_LINKS]:
        u = (u or "").strip()
        if not u:
            continue
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
            u = f"https://{u}"
        seed_urls.append(u)

    if not seed_urls:
        return ""

    logger.info(
        f"[LinkScraper] Deep crawl starting | seeds={len(seed_urls)} "
        f"max_pages_per_seed={MAX_INTERNAL_LINKS_PER_SEED + 1} "
        f"global_cap={MAX_TOTAL_PAGES}"
    )

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    async with httpx.AsyncClient(
        headers=_REQUEST_HEADERS,
        http2=False,
        verify=True,
        limits=httpx.Limits(
            max_connections=MAX_CONCURRENT_FETCHES,
            max_keepalive_connections=MAX_CONCURRENT_FETCHES,
        ),
    ) as client:
        # Crawl seeds sequentially so each seed's budget reflects what
        # the previous one already consumed. Within a seed, internal
        # links are still fetched concurrently (bounded by ``sem``).
        all_pages: List[Tuple[str, str]] = []
        budget = MAX_TOTAL_PAGES
        for seed_url in seed_urls:
            if budget <= 0:
                logger.info(
                    f"[LinkScraper] Global page budget exhausted, "
                    f"skipping remaining seeds"
                )
                break
            pages = await _crawl_seed(
                client, seed_url, remaining_budget=budget, sem=sem,
            )
            all_pages.extend(pages)
            budget -= len(pages)

    if not all_pages:
        logger.warning(
            "[LinkScraper] No content extracted from any of the supplied "
            "links. Common causes: 403 bot challenge, JS-only SPA with "
            "empty static HTML, or non-HTML content-type."
        )
        return ""

    deduped = _dedupe_pages(all_pages)
    if len(deduped) < len(all_pages):
        logger.info(
            f"[LinkScraper] De-duplicated {len(all_pages) - len(deduped)} "
            f"near-identical pages"
        )

    # Build the combined corpus, capping at MAX_TOTAL_CHARS.
    sections: List[str] = []
    total = 0
    for url, text in deduped:
        section = f"--- Content from {url} ---\n{text}"
        if total + len(section) > MAX_TOTAL_CHARS:
            # take whatever still fits, then stop
            remaining = MAX_TOTAL_CHARS - total
            if remaining > 200:
                sections.append(section[:remaining])
            break
        sections.append(section)
        total += len(section) + 2  # +2 for the "\n\n" separator below

    combined = "\n\n".join(sections)
    logger.info(
        f"[LinkScraper] Deep crawl complete | pages={len(deduped)} "
        f"chars={len(combined)} | sources={[u for u, _ in deduped]}"
    )
    return combined
