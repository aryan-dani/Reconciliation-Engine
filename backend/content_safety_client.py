"""Azure AI Content Safety (Text) client.

Purpose in this repo:
- Ensure AI-generated explanations are enterprise-safe before they are persisted or shown.
- Provide a second Microsoft AI service alongside Azure AI Foundry.

Configuration (env vars):
- AZURE_CONTENT_SAFETY_ENDPOINT: e.g. https://<resource>.cognitiveservices.azure.com
- AZURE_CONTENT_SAFETY_API_KEY: key for the Content Safety resource
- AZURE_CONTENT_SAFETY_API_VERSION: optional, default 2023-10-01
- CONTENT_SAFETY_SEVERITY_THRESHOLD: optional int, default 4 (block if >= threshold)

This module is defensive: failures return a structured error payload and callers
must continue operating.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, cast

import requests


_DEFAULT_API_VERSION = "2023-10-01"
_DEFAULT_THRESHOLD = 4
_DEFAULT_CATEGORIES = ["Hate", "SelfHarm", "Sexual", "Violence"]


def _try_load_dotenv() -> None:
    """Load env vars from backend/.env for local demos."""

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(backend_dir, ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = (_env(name) or "").strip()
    try:
        return int(raw)
    except Exception:
        return default


def contentsafety_is_configured() -> bool:
    _try_load_dotenv()
    return bool(_env("AZURE_CONTENT_SAFETY_ENDPOINT") and _env("AZURE_CONTENT_SAFETY_API_KEY"))


@dataclass(frozen=True)
class ContentSafetyResult:
    enabled: bool
    ok: bool
    allowed: bool
    max_severity: Optional[int]
    categories: Optional[Any]
    status_code: Optional[int]
    error_code: Optional[str]
    error_type: Optional[str]
    hint: Optional[Any]
    analyzed_at: float


def _contract(
    *,
    enabled: bool,
    ok: bool,
    allowed: bool,
    max_severity: Optional[int],
    categories: Optional[Any],
    status_code: Optional[int],
    error_code: Optional[str],
    error_type: Optional[str],
    hint: Optional[Any],
) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "ok": ok,
        "allowed": allowed,
        "max_severity": max_severity,
        "categories": categories,
        "status_code": status_code,
        "error_code": error_code,
        "error_type": error_type,
        "hint": hint,
        "analyzed_at": time.time(),
    }


def _normalize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    return endpoint


def analyze_text_safety(*, trace_id: str, text: str) -> Dict[str, Any]:
    """Analyze text using Azure AI Content Safety.

    Returns a structured dict:
    - enabled/ok
    - allowed boolean (policy decision)
    - severity breakdown

    If not configured, returns enabled=False.
    """

    _try_load_dotenv()

    endpoint = _env("AZURE_CONTENT_SAFETY_ENDPOINT")
    api_key = _env("AZURE_CONTENT_SAFETY_API_KEY")
    if not (endpoint and api_key):
        return _contract(
            enabled=False,
            ok=False,
            allowed=False,
            max_severity=None,
            categories=None,
            status_code=None,
            error_code="NOT_CONFIGURED",
            error_type=None,
            hint="Missing AZURE_CONTENT_SAFETY_ENDPOINT or AZURE_CONTENT_SAFETY_API_KEY",
        )

    api_version = _env("AZURE_CONTENT_SAFETY_API_VERSION", _DEFAULT_API_VERSION) or _DEFAULT_API_VERSION
    threshold = _env_int("CONTENT_SAFETY_SEVERITY_THRESHOLD", _DEFAULT_THRESHOLD)

    url = f"{_normalize_endpoint(endpoint)}/contentsafety/text:analyze?api-version={api_version}"

    payload: Dict[str, Any] = {
        "text": text or "",
        "categories": list(_DEFAULT_CATEGORIES),
    }

    headers = {
        # Different Azure services accept different header names; send both.
        "Ocp-Apim-Subscription-Key": api_key,
        "api-key": api_key,
        "Content-Type": "application/json",
        "User-Agent": "reconciliation-engine/contentsafety",
        "x-ms-client-request-id": trace_id,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=8.0)
        status = resp.status_code
        if status < 200 or status >= 300:
            # Avoid leaking response body if it contains details.
            return _contract(
                enabled=True,
                ok=False,
                allowed=False,
                max_severity=None,
                categories=None,
                status_code=status,
                error_code="CONTENT_SAFETY_HTTP_ERROR",
                error_type="HttpError",
                hint={"trace_id": trace_id},
            )

        data = cast(Dict[str, Any], resp.json())
        analyses = data.get("categoriesAnalysis")
        max_sev: Optional[int] = None
        if isinstance(analyses, list):
            for item in analyses:
                if not isinstance(item, dict):
                    continue
                sev = item.get("severity")
                if isinstance(sev, int):
                    if max_sev is None or sev > max_sev:
                        max_sev = sev

        # Policy: block if any category severity meets/exceeds threshold.
        allowed = True
        if max_sev is not None and max_sev >= threshold:
            allowed = False

        return _contract(
            enabled=True,
            ok=True,
            allowed=allowed,
            max_severity=max_sev,
            categories=analyses,
            status_code=status,
            error_code=None,
            error_type=None,
            hint={"threshold": threshold, "trace_id": trace_id},
        )

    except Exception as e:
        return _contract(
            enabled=True,
            ok=False,
            allowed=False,
            max_severity=None,
            categories=None,
            status_code=None,
            error_code="CONTENT_SAFETY_EXCEPTION",
            error_type=type(e).__name__,
            hint={"trace_id": trace_id},
        )


def probe_contentsafety_status() -> Dict[str, Any]:
    """Lightweight probe to validate credentials + endpoint."""

    return analyze_text_safety(trace_id="contentsafety-probe", text="health check")
