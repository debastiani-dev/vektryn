from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import ipaddress
import json
import logging
import re
import secrets
import socket
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from uuid import UUID

from bs4 import BeautifulSoup
from django.conf import settings
import httpx
import redis

from apps.jobs.models.jobs import JobPosting
from apps.resumes.models.resumes import ResumeProfile
from apps.resumes.services.rescore_publisher import (
    current_trace_id,
    publish_rescore_event,
)
from vektryn_contracts import (
    ATSSource,
    JobRescoreEvent,
    compute_job_content_hash,
    validate_apply_url,
)

logger = logging.getLogger(__name__)

_MAILTO_PREFIX = "mailto:"
_HTML_PARSER = "html.parser"
_UTF8 = "utf-8"

_DATA_NODE_VPC_SUBNET = ipaddress.ip_network("10.8.0.0/24")
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({None, 80, 443})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
_TRACKING_QUERY_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "gh_src",
        "mc_cid",
        "mc_eid",
        "ref",
        "refid",
        "trk",
        "trkinfo",
    }
)
_HOSTED_ATS_PATH_HOSTS = frozenset(
    {
        "job-boards.greenhouse.io",
        "boards.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
        "apply.workable.com",
        "jobs.smartrecruiters.com",
    }
)
_GENERIC_SUBDOMAINS = (
    "www.",
    "careers.",
    "jobs.",
    "apply.",
    "hire.",
    "boards.",
    "job-boards.",
)
_GENERIC_SITE_NAMES = frozenset(
    {
        "greenhouse",
        "job boards",
        "lever",
        "ashby",
        "workable",
        "smartrecruiters",
        "linkedin",
    }
)
_LINKEDIN_HIRING_MARKERS = (
    " hiring ",
    " está contratando ",
    " esta contratando ",
    " contratando ",
    " busca ",
    " recrutando ",
)
_LINKEDIN_AUTHWALL_PATHS = ("/authwall", "/login", "/uas/login", "/checkpoint/")
_LINKEDIN_SLUG_COMPANY_RE = re.compile(r"-at-([a-z0-9-]+?)(?:-\d+)?$")
_COUNTRY_SUBDOMAIN_RE = re.compile(r"^[a-z]{2}\.")
_STRIPPED_HTML_TAGS = ("script", "style", "noscript", "svg", "iframe")
_CHROME_HTML_TAGS = ("nav", "header", "footer", "aside")

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_SNAPSHOT_HTML_BYTES = 256 * 1024  # 256 KiB
MIN_EXTRACTED_DESCRIPTION_CHARS = 80
EXTERNAL_FETCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
STREAM_EDGE_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
IMPORT_RATE_LIMIT_MAX = 10
IMPORT_RATE_LIMIT_WINDOW_SECONDS = 300
_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; VektrynJobImportBot/1.0; +https://vektryn.debastiani.dev)"
)

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class ManualImportValidationError(ValueError):
    """Raised when URL, email, or SSRF validation fails (HTTP 400)."""


class ManualImportFetchError(RuntimeError):
    """Raised when an external job page cannot be fetched or parsed (HTTP 422)."""


class ManualImportRateLimitError(RuntimeError):
    """Raised when a user exceeds the manual import rate limit (HTTP 429)."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"Too many manual job imports. Please retry in {self.retry_after}s."
        )


class ManualImportIngestError(RuntimeError):
    """Raised when Stream Edge ingestion fails or is unavailable (HTTP 503)."""


@dataclass(frozen=True)
class ValidatedTarget:
    logical_url: str
    scheme: str
    ascii_host: str
    port: int | None
    pinned_ip: str
    pinned_url: str
    host_header: str


@dataclass(frozen=True)
class ExtractedJob:
    title: str
    company_name: str
    location_raw: str
    description_clean: str
    raw_html_snapshot: str
    posted_at: datetime | None = None


@dataclass(frozen=True)
class _PreparedImport:
    title: str
    company_name: str
    apply_url: str
    location_raw: str
    description_clean: str
    raw_html_snapshot: str
    posted_at: datetime | None = None


@dataclass(frozen=True)
class ManualImportResult:
    status: str  # "queued" | "already_exists" | "reactivated"
    ats_source: str
    external_id: str
    content_hash: str
    title: str
    company_name: str
    apply_url: str
    event_id: str | None = None
    job_posting_uuid: UUID | None = None


def _unwrap_ip(raw_ip: IPAddress) -> IPAddress:
    if isinstance(raw_ip, ipaddress.IPv6Address) and raw_ip.ipv4_mapped is not None:
        return raw_ip.ipv4_mapped
    return raw_ip


def _assert_ip_is_public(raw_ip: IPAddress) -> IPAddress:
    ip = _unwrap_ip(raw_ip)
    if isinstance(ip, ipaddress.IPv4Address) and ip in _DATA_NODE_VPC_SUBNET:
        raise ManualImportValidationError(
            "Private or internal network URLs are not permitted."
        )
    if (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ManualImportValidationError(
            "Private, loopback, or non-public network URLs are not permitted."
        )
    return ip


def _parse_and_validate_url_parts(url: str) -> tuple[str, str, int | None, str, str]:
    raw = (url or "").strip()
    if not raw or len(raw) > 512:
        raise ManualImportValidationError(
            "URL must be a non-empty http/https link up to 512 characters."
        )
    if any(ch in raw for ch in ("\r", "\n", "\x00")):
        raise ManualImportValidationError("URL contains invalid control characters.")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ManualImportValidationError("Only http and https URLs are permitted.")
    if parsed.username is not None or parsed.password is not None:
        raise ManualImportValidationError("URLs with embedded credentials are blocked.")

    hostname = (parsed.hostname or "").strip().rstrip(".")
    if not hostname:
        raise ManualImportValidationError("URL must include a valid hostname.")

    port = _validate_port(parsed)
    ascii_host = _validate_hostname(hostname)
    return scheme, ascii_host, port, parsed.path or "/", parsed.query


def _validate_port(parsed) -> int | None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise ManualImportValidationError("URL contains an invalid port.") from exc
    if port not in _ALLOWED_PORTS:
        raise ManualImportValidationError(
            "Only standard HTTP (80) and HTTPS (443) ports are permitted."
        )
    return port


def _validate_hostname(hostname: str) -> str:
    lowered = hostname.lower()
    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ManualImportValidationError(
            "Localhost and internal metadata hostnames are not permitted."
        )
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ManualImportValidationError(
            "URL hostname is not valid ASCII/IDNA."
        ) from exc


def _resolve_and_validate_ips(ascii_host: str, resolved_port: int) -> list[IPAddress]:
    try:
        literal_ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        return [_assert_ip_is_public(literal_ip)]

    try:
        addrinfo = socket.getaddrinfo(
            ascii_host, resolved_port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ManualImportValidationError(
            f"Could not resolve hostname '{ascii_host}'."
        ) from exc

    if not addrinfo:
        raise ManualImportValidationError(
            f"Hostname '{ascii_host}' did not resolve to any IP addresses."
        )

    return [
        _assert_ip_is_public(ipaddress.ip_address(sockaddr[0]))
        for _family, _socktype, _proto, _canonname, sockaddr in addrinfo
    ]


def _build_validated_target(
    *,
    scheme: str,
    ascii_host: str,
    port: int | None,
    path: str,
    query: str,
    validated_ips: list[IPAddress],
) -> ValidatedTarget:
    chosen_ip = next(
        (ip for ip in validated_ips if isinstance(ip, ipaddress.IPv4Address)),
        validated_ips[0],
    )
    pinned_ip_str = str(chosen_ip)
    pinned_host = (
        f"[{pinned_ip_str}]"
        if isinstance(chosen_ip, ipaddress.IPv6Address)
        else pinned_ip_str
    )
    pinned_netloc = f"{pinned_host}:{port}" if port is not None else pinned_host
    pinned_url = urlunparse((scheme, pinned_netloc, path, "", query, ""))

    host_part = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    host_header = f"{host_part}:{port}" if port is not None else host_part
    logical_url = urlunparse((scheme, host_header, path, "", query, ""))
    return ValidatedTarget(
        logical_url=logical_url,
        scheme=scheme,
        ascii_host=ascii_host,
        port=port,
        pinned_ip=pinned_ip_str,
        pinned_url=pinned_url,
        host_header=host_header,
    )


def validate_public_http_url(url: str) -> ValidatedTarget:
    scheme, ascii_host, port, path, query = _parse_and_validate_url_parts(url)
    resolved_port = port or (443 if scheme == "https" else 80)
    validated_ips = _resolve_and_validate_ips(ascii_host, resolved_port)
    return _build_validated_target(
        scheme=scheme,
        ascii_host=ascii_host,
        port=port,
        path=path,
        query=query,
        validated_ips=validated_ips,
    )


def canonicalize_http_url(url: str) -> str:
    parsed = urlparse(url.strip())
    kept_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_QUERY_PARAMS
    ]
    kept_query.sort()
    netloc = (parsed.hostname or "").lower()
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if parsed.port is not None and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (parsed.scheme.lower(), netloc, path, "", urlencode(kept_query), "")
    )


def normalize_apply_target(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ManualImportValidationError(
            "An application URL or email address is required."
        )

    lowered = raw.lower()
    is_email_like = lowered.startswith(_MAILTO_PREFIX) or (
        "@" in raw and "://" not in raw and not lowered.startswith(("http:", "https:"))
    )
    if is_email_like:
        candidate = (
            raw if lowered.startswith(_MAILTO_PREFIX) else f"{_MAILTO_PREFIX}{raw}"
        )
        try:
            return validate_apply_url(candidate)
        except ValueError as exc:
            raise ManualImportValidationError(
                "Please enter a valid email address or public http/https application URL."
            ) from exc

    target = validate_public_http_url(raw)
    try:
        return validate_apply_url(target.logical_url)
    except ValueError as exc:
        raise ManualImportValidationError(str(exc)) from exc


def build_manual_external_id(*, apply_url: str, title: str, company_name: str) -> str:
    if apply_url.lower().startswith(_MAILTO_PREFIX):
        seed = "|".join(
            [
                apply_url.lower(),
                " ".join(title.lower().split()),
                " ".join(company_name.lower().split()),
            ]
        )
    else:
        seed = canonicalize_http_url(apply_url)
    digest = hashlib.sha256(seed.encode(_UTF8)).hexdigest()[:24]
    return f"manual-{digest}"


def build_manual_snapshot_html(
    *,
    title: str,
    company_name: str,
    location_raw: str,
    description_clean: str,
) -> str:
    location_block = (
        f"<p class='location'>{html.escape(location_raw)}</p>" if location_raw else ""
    )
    return (
        "<article class='vektryn-manual-import'>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p class='company'>{html.escape(company_name)}</p>"
        f"{location_block}"
        f"<pre>{html.escape(description_clean)}</pre>"
        "</article>"
    )


def _build_pinned_request(
    http_client: httpx.Client, target: ValidatedTarget
) -> httpx.Request:
    extensions: dict[str, Any] = {}
    if target.scheme == "https":
        # Verified against httpcore 1.0.9 (httpx 0.28.1): SyncStream.start_tls
        # accepts ASCII/IDNA str for server_hostname.
        extensions["sni_hostname"] = target.ascii_host
    return http_client.build_request(
        "GET",
        target.pinned_url,
        headers={
            "Host": target.host_header,
            "User-Agent": _FETCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
        },
        extensions=extensions,
    )


def _read_bounded_response(response: httpx.Response) -> str:
    if response.status_code >= 400:
        raise ManualImportFetchError(
            f"Target site returned HTTP {response.status_code}. "
            "Some job boards block automated fetches — switch to Enter Manually to paste the description."
        )

    raw_ct = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if raw_ct and raw_ct not in _ALLOWED_CONTENT_TYPES:
        raise ManualImportFetchError(
            f"Unsupported content type '{raw_ct}'. Provide an HTML job page URL or switch to Enter Manually."
        )

    chunks: list[bytes] = []
    total_bytes = 0
    for chunk in response.iter_bytes():
        total_bytes += len(chunk)
        if total_bytes > MAX_RESPONSE_BYTES:
            raise ManualImportFetchError(
                "Target page exceeds the 2 MB fetch limit. Switch to Enter Manually to paste the description."
            )
        chunks.append(chunk)

    encoding = response.encoding or _UTF8
    return b"".join(chunks).decode(encoding, errors="replace")


def _send_pinned_request(
    http_client: httpx.Client, target: ValidatedTarget
) -> httpx.Response:
    request = _build_pinned_request(http_client, target)
    try:
        return http_client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise ManualImportFetchError(
            f"Could not fetch job page ({exc.__class__.__name__}). "
            "Switch to Enter Manually to paste the job description."
        ) from exc


def _is_linkedin_host(host: str) -> bool:
    normalized = host.lower().strip(".")
    return normalized == "linkedin.com" or normalized.endswith(".linkedin.com")


def normalize_import_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not _is_linkedin_host(host):
        return raw
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() == "currentjobid" and value.strip().isdigit():
            return f"https://www.linkedin.com/jobs/view/{value.strip()}/"
    return raw


def _assert_not_linkedin_authwall(logical_url: str) -> None:
    parsed = urlparse(logical_url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if _is_linkedin_host(host) and path.startswith(_LINKEDIN_AUTHWALL_PATHS):
        raise ManualImportFetchError(
            "LinkedIn redirected this listing to a sign-in wall. "
            "Switch to Enter Manually to paste the job description."
        )


def fetch_public_job_page(
    url: str, *, client: httpx.Client | None = None
) -> tuple[str, str]:
    logical_url = normalize_import_url(url)
    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=EXTERNAL_FETCH_TIMEOUT,
        follow_redirects=False,
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            target = validate_public_http_url(logical_url)
            response = _send_pinned_request(http_client, target)
            try:
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = (response.headers.get("location") or "").strip()
                    if not location:
                        raise ManualImportFetchError(
                            "Target site returned an empty redirect."
                        )
                    # Resolve relative redirects against logical hostname URL, never the pinned IP
                    logical_url = urljoin(target.logical_url, location)
                    continue
                _assert_not_linkedin_authwall(target.logical_url)
                return _read_bounded_response(response), target.logical_url
            finally:
                response.close()

        raise ManualImportFetchError(
            "Too many redirects while fetching the job posting URL."
        )
    finally:
        if owns_client:
            http_client.close()


def _iter_json_ld_objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found.extend(_iter_json_ld_objects(item))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_json_ld_objects(item))
    return found


def _is_job_posting_type(raw_type: Any) -> bool:
    if isinstance(raw_type, str):
        return raw_type.strip().lower() == "jobposting"
    if isinstance(raw_type, list):
        return any(
            isinstance(item, str) and item.strip().lower() == "jobposting"
            for item in raw_type
        )
    return False


def _format_address_field(address: Any) -> str:
    if isinstance(address, str):
        return address.strip()
    if not isinstance(address, dict):
        return ""
    tokens = [
        str(address.get(key) or "").strip()
        for key in ("addressLocality", "addressRegion", "addressCountry")
        if str(address.get(key) or "").strip()
    ]
    return ", ".join(tokens)


def _extract_json_ld_location(posting: dict[str, Any]) -> str:
    parts: list[str] = []
    if str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        parts.append("Remote")

    raw_locations = posting.get("jobLocation")
    locations = [raw_locations] if isinstance(raw_locations, dict) else raw_locations
    if isinstance(locations, list):
        for loc in locations:
            formatted = (
                _format_address_field(loc.get("address"))
                if isinstance(loc, dict)
                else ""
            )
            if formatted:
                parts.append(formatted)

    deduped = list(dict.fromkeys(parts))
    return " · ".join(deduped)[:255]


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _clean_html_fragment(fragment: str) -> str:
    unescaped = html.unescape(fragment or "")
    frag_soup = BeautifulSoup(unescaped, _HTML_PARSER)
    for tag in frag_soup(_STRIPPED_HTML_TAGS):
        tag.decompose()
    lines = [
        line.strip() for line in frag_soup.get_text("\n").splitlines() if line.strip()
    ]
    return "\n".join(lines)


def _humanize_slug(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _extract_linkedin_company_from_url(parsed) -> str:
    segments = [seg.strip().lower() for seg in parsed.path.split("/") if seg.strip()]
    if len(segments) < 3 or segments[0] != "jobs" or segments[1] != "view":
        return ""
    match = _LINKEDIN_SLUG_COMPANY_RE.search(segments[2])
    if not match:
        return ""
    return _humanize_slug(match.group(1))


def _strip_subdomains(host: str) -> str:
    cleaned = host
    for prefix in _GENERIC_SUBDOMAINS:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    if cleaned.count(".") >= 2 and _COUNTRY_SUBDOMAIN_RE.match(cleaned):
        cleaned = cleaned[3:]
    return cleaned


def _fallback_company_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _is_linkedin_host(host):
        linkedin_company = _extract_linkedin_company_from_url(parsed)
        if linkedin_company:
            return linkedin_company
    if host in _HOSTED_ATS_PATH_HOSTS:
        segments = [seg.strip() for seg in parsed.path.split("/") if seg.strip()]
        if segments:
            return _humanize_slug(segments[0]) or "External"
    cleaned_host = _strip_subdomains(host)
    primary = cleaned_host.split(".")[0] if cleaned_host else "External"
    return _humanize_slug(primary) or "External"


def _strip_title_suffix(page_title: str) -> str:
    cleaned = page_title.strip()
    for sep in (" | ", " - ", " — "):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()
    return cleaned


def _extract_company_from_title(page_title: str) -> str:
    cleaned = _strip_title_suffix(page_title)
    if not cleaned:
        return ""
    lower = cleaned.lower()

    for marker in _LINKEDIN_HIRING_MARKERS:
        idx = lower.find(marker)
        if idx > 0:
            candidate = cleaned[:idx].strip()
            if candidate and candidate.lower() not in _GENERIC_SITE_NAMES:
                return candidate[:180]

    at_idx = lower.rfind(" at ")
    if at_idx == -1:
        return ""
    candidate = cleaned[at_idx + 4 :].strip()
    if not candidate or candidate.lower() in _GENERIC_SITE_NAMES:
        return ""
    return candidate[:180]


def _find_json_ld_job_posting(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = (script_tag.string or script_tag.get_text() or "").strip()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
        except ValueError:
            continue
        for obj in _iter_json_ld_objects(parsed):
            if _is_job_posting_type(obj.get("@type")):
                return obj
    return None


def _extract_json_ld_company(hiring_org: Any) -> str:
    if isinstance(hiring_org, dict):
        return str(hiring_org.get("name") or "").strip()
    if isinstance(hiring_org, str):
        return hiring_org.strip()
    return ""


def _extract_json_ld_fields(
    posting: dict[str, Any] | None,
) -> tuple[str, str, str, str, datetime | None]:
    if posting is None:
        return "", "", "", "", None
    title = str(posting.get("title") or posting.get("name") or "").strip()
    company = _extract_json_ld_company(posting.get("hiringOrganization"))
    location = _extract_json_ld_location(posting)
    raw_desc = posting.get("description")
    description = (
        _clean_html_fragment(raw_desc)
        if isinstance(raw_desc, str) and raw_desc.strip()
        else ""
    )
    posted_at = _parse_iso_datetime(posting.get("datePosted"))
    return title, company, location, description, posted_at


def _extract_meta_hints(soup: BeautifulSoup) -> tuple[str, str, str, str]:
    og_title_tag = soup.find("meta", attrs={"property": "og:title"})
    og_site_tag = soup.find("meta", attrs={"property": "og:site_name"})
    h1_tag = soup.find("h1")
    title_tag = soup.find("title")

    meta_title = (
        str(og_title_tag.get("content") or "").strip()
        if og_title_tag is not None
        else ""
    )
    raw_meta_company = (
        str(og_site_tag.get("content") or "").strip() if og_site_tag is not None else ""
    )
    meta_company = (
        "" if raw_meta_company.lower() in _GENERIC_SITE_NAMES else raw_meta_company
    )
    h1_text = h1_tag.get_text(" ", strip=True) if h1_tag is not None else ""
    page_title = title_tag.get_text(" ", strip=True) if title_tag is not None else ""
    return meta_title, meta_company, h1_text, page_title


def _prune_and_build_snapshot(soup: BeautifulSoup) -> str:
    for tag in soup(_STRIPPED_HTML_TAGS):
        tag.decompose()
    snapshot_html = str(soup).strip()
    encoded = snapshot_html.encode(_UTF8)
    if len(encoded) > MAX_SNAPSHOT_HTML_BYTES:
        return encoded[:MAX_SNAPSHOT_HTML_BYTES].decode(_UTF8, errors="ignore").strip()
    return snapshot_html


def _extract_fallback_description(soup: BeautifulSoup) -> str:
    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    content_copy = BeautifulSoup(str(content_root), _HTML_PARSER)
    for chrome in content_copy(_CHROME_HTML_TAGS):
        chrome.decompose()
    lines = [
        line.strip()
        for line in content_copy.get_text("\n").splitlines()
        if line.strip()
    ]
    return "\n".join(lines)


def extract_job_from_html(
    raw_html: str,
    final_url: str,
    *,
    title_override: str = "",
    company_override: str = "",
    location_override: str = "",
) -> ExtractedJob:
    soup = BeautifulSoup(raw_html or "", _HTML_PARSER)
    ld_title, ld_company, ld_location, ld_description, ld_posted_at = (
        _extract_json_ld_fields(_find_json_ld_job_posting(soup))
    )
    meta_title, meta_company, h1_text, page_title = _extract_meta_hints(soup)
    snapshot_html = _prune_and_build_snapshot(soup)

    description_clean = ld_description
    if len(description_clean) < MIN_EXTRACTED_DESCRIPTION_CHARS:
        fallback_text = _extract_fallback_description(soup)
        if len(fallback_text) > len(description_clean):
            description_clean = fallback_text

    if len(description_clean.strip()) < MIN_EXTRACTED_DESCRIPTION_CHARS:
        raise ManualImportFetchError(
            "Could not extract enough job description text from this URL "
            "(the page may require JavaScript or login). Switch to Enter Manually to paste the description."
        )

    title = (
        title_override.strip()
        or ld_title
        or h1_text
        or meta_title
        or page_title
        or "Imported Role"
    )[:255]
    company_name = (
        company_override.strip()
        or ld_company
        or meta_company
        or _extract_company_from_title(page_title)
        or _fallback_company_from_url(final_url)
    )[:180]
    location_raw = (location_override.strip() or ld_location)[:255]

    if not snapshot_html:
        snapshot_html = build_manual_snapshot_html(
            title=title,
            company_name=company_name,
            location_raw=location_raw,
            description_clean=description_clean,
        )

    return ExtractedJob(
        title=title,
        company_name=company_name,
        location_raw=location_raw,
        description_clean=description_clean,
        raw_html_snapshot=snapshot_html,
        posted_at=ld_posted_at,
    )


def enforce_import_rate_limit(user_id: int | str) -> None:
    redis_url = getattr(settings, "REDIS_URL", "").strip()
    if not redis_url:
        return
    key = f"vektryn:manual-import:rl:{user_id}"
    client = None
    try:
        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
            decode_responses=True,
        )
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, IMPORT_RATE_LIMIT_WINDOW_SECONDS)
        if count > IMPORT_RATE_LIMIT_MAX:
            ttl = client.ttl(key)
            raise ManualImportRateLimitError(
                retry_after=(
                    ttl if ttl and ttl > 0 else IMPORT_RATE_LIMIT_WINDOW_SECONDS
                )
            )
    except ManualImportRateLimitError:
        raise
    except Exception as exc:
        logger.warning("Redis unavailable for manual import rate limit: %s", exc)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


class ManualJobImportService:
    def __init__(self, user) -> None:
        self.user = user

    def _enqueue_rescore_for_reactivated_job(self) -> None:
        active_profiles = ResumeProfile.objects.filter(
            user=self.user,
            is_active=True,
            embedding__isnull=False,
        ).only("uuid")
        trace_id = current_trace_id()
        for profile in active_profiles:
            event = JobRescoreEvent(
                trace_id=trace_id,
                resume_profile_uuid=profile.uuid,
                user_id=self.user.pk,
                max_jobs=50,
                force=False,
            )
            try:
                publish_rescore_event(event, require_broker=False)
            except Exception as exc:
                logger.warning(
                    "Best-effort rescore after manual job reactivation failed: %s", exc
                )

    def _forward_to_stream_edge(
        self,
        *,
        external_id: str,
        title: str,
        company_name: str,
        apply_url: str,
        location_raw: str,
        raw_html: str,
        description_clean: str,
        posted_at: datetime | None,
    ) -> dict[str, Any]:
        edge_base_url = getattr(settings, "STREAM_EDGE_URL", "").strip().rstrip("/")
        if not edge_base_url:
            raise ManualImportIngestError(
                "STREAM_EDGE_URL is not configured on Control Plane."
            )

        ingest_api_key = getattr(settings, "INGEST_API_KEY", "").strip()
        trace_id = current_trace_id()
        headers = {
            "traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01",
        }
        if ingest_api_key:
            headers["X-Ingest-API-Key"] = ingest_api_key

        payload: dict[str, Any] = {
            "ats_source": ATSSource.MANUAL.value,
            "external_id": external_id,
            "title": title,
            "company_name": company_name,
            "apply_url": apply_url,
            "location_raw": location_raw,
            "raw_html": raw_html,
            "description_clean": description_clean,
            "posted_at": posted_at.isoformat() if posted_at is not None else None,
        }

        try:
            with httpx.Client(timeout=STREAM_EDGE_TIMEOUT) as client:
                response = client.post(
                    f"{edge_base_url}/ingest/jobs",
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise ManualImportIngestError(
                f"Stream Edge ingestion service is unavailable ({exc.__class__.__name__})."
            ) from exc

        if response.status_code not in {200, 202}:
            raise ManualImportIngestError(
                f"Stream Edge rejected manual job payload (HTTP {response.status_code})."
            )
        return response.json()

    def _prepare_import(self, validated_data: dict[str, Any]) -> _PreparedImport:
        url_input = (validated_data.get("url") or "").strip()
        if url_input:
            raw_html, final_url = fetch_public_job_page(url_input)
            extracted = extract_job_from_html(
                raw_html,
                final_url,
                title_override=validated_data.get("title") or "",
                company_override=validated_data.get("company_name") or "",
                location_override=validated_data.get("location_raw") or "",
            )
            return _PreparedImport(
                title=extracted.title,
                company_name=extracted.company_name,
                apply_url=final_url,
                location_raw=extracted.location_raw,
                description_clean=extracted.description_clean,
                raw_html_snapshot=extracted.raw_html_snapshot,
                posted_at=extracted.posted_at,
            )

        title = (validated_data.get("title") or "").strip()[:255]
        company_name = (validated_data.get("company_name") or "").strip()[:180]
        location_raw = (validated_data.get("location_raw") or "").strip()[:255]
        description_clean = (validated_data.get("description") or "").strip()
        apply_url = normalize_apply_target(validated_data.get("apply_url") or "")
        return _PreparedImport(
            title=title,
            company_name=company_name,
            apply_url=apply_url,
            location_raw=location_raw,
            description_clean=description_clean,
            raw_html_snapshot=build_manual_snapshot_html(
                title=title,
                company_name=company_name,
                location_raw=location_raw,
                description_clean=description_clean,
            ),
            posted_at=None,
        )

    def _handle_existing_by_hash(self, existing: JobPosting) -> ManualImportResult:
        if existing.is_deleted or not existing.is_active:
            existing.is_deleted = False
            existing.is_active = True
            existing.closed_at = None
            existing.save(update_fields=["is_deleted", "is_active", "closed_at"])
            if existing.embedding is not None:
                self._enqueue_rescore_for_reactivated_job()
            status_value = "reactivated"
        else:
            status_value = "already_exists"

        return ManualImportResult(
            status=status_value,
            ats_source=existing.ats_source,
            external_id=existing.external_id,
            content_hash=existing.content_hash,
            title=existing.title,
            company_name=existing.company_name,
            apply_url=existing.apply_url,
            job_posting_uuid=existing.uuid,
        )

    def import_job(self, validated_data: dict[str, Any]) -> ManualImportResult:
        enforce_import_rate_limit(self.user.pk)
        prepared = self._prepare_import(validated_data)

        external_id = build_manual_external_id(
            apply_url=prepared.apply_url,
            title=prepared.title,
            company_name=prepared.company_name,
        )
        content_hash = compute_job_content_hash(
            ats_source=ATSSource.MANUAL,
            title=prepared.title,
            company_name=prepared.company_name,
            description_clean=prepared.description_clean,
        )

        # Inspect ALL rows (including closed & soft-deleted) to respect UNIQUE(content_hash)
        # and avoid silent 7-day Redis dedup drops or matcher-worker DLQ collisions.
        existing_by_hash = JobPosting.all_objects.filter(
            content_hash=content_hash
        ).first()
        if existing_by_hash is not None:
            return self._handle_existing_by_hash(existing_by_hash)

        ingest_resp = self._forward_to_stream_edge(
            external_id=external_id,
            title=prepared.title,
            company_name=prepared.company_name,
            apply_url=prepared.apply_url,
            location_raw=prepared.location_raw,
            raw_html=prepared.raw_html_snapshot,
            description_clean=prepared.description_clean,
            posted_at=prepared.posted_at,
        )
        return ManualImportResult(
            status="queued",
            ats_source=ATSSource.MANUAL.value,
            external_id=external_id,
            content_hash=str(ingest_resp.get("content_hash") or content_hash),
            title=prepared.title,
            company_name=prepared.company_name,
            apply_url=prepared.apply_url,
            event_id=str(ingest_resp.get("event_id") or "") or None,
        )
