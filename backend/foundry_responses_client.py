"""Azure AI Foundry inference via the OpenAI *Responses API*.

Why Responses API:
- The OpenAI platform is converging on the Responses API as the durable, future-proof interface.
- It supports structured outputs (JSON Schema) in a first-class way.

How deployment-backed inference works:
- In Azure AI Foundry, you invoke a *deployment* (a named, managed model instance).
- This code always targets a deployment name (AZURE_FOUNDRY_DEPLOYMENT), never a raw model name.

Hard constraints enforced by design:
- Only the Azure AI Foundry Responses API is used.
- Only these environment variables are read:
    - AZURE_FOUNDRY_ENDPOINT
    - AZURE_FOUNDRY_API_KEY
    - AZURE_FOUNDRY_DEPLOYMENT

This module is defensive: failures return a structured error payload and callers
must continue reconciliation without AI.
"""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import urlparse
from typing import Any, Dict, Optional, cast


logger = logging.getLogger(__name__)


# Azure OpenAI only enables the Responses API starting at 2025-03-01-preview.
_AZURE_API_VERSION = "2025-03-01-preview"
_DEFAULT_DEPLOYMENT = "recon-gpt-responses"


def _try_load_dotenv() -> None:
    """Load env vars from backend/.env for local demos.

    In production you should set environment variables externally.
    """

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


def foundry_is_configured() -> bool:
    _try_load_dotenv()
    return bool(_env("AZURE_FOUNDRY_ENDPOINT") and _env("AZURE_FOUNDRY_API_KEY") and _env("AZURE_FOUNDRY_DEPLOYMENT"))


def _validate_config() -> Optional[str]:
    _try_load_dotenv()
    endpoint = _env("AZURE_FOUNDRY_ENDPOINT")
    api_key = _env("AZURE_FOUNDRY_API_KEY")
    deployment = _env("AZURE_FOUNDRY_DEPLOYMENT")
    if not (endpoint and api_key and deployment):
        return "Missing AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_API_KEY, or AZURE_FOUNDRY_DEPLOYMENT"

    try:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"https"} or not parsed.netloc:
            return "AZURE_FOUNDRY_ENDPOINT must be a full https URL (e.g., https://<resource>.openai.azure.com or https://<project>.services.ai.azure.com)"
    except Exception:
        return "AZURE_FOUNDRY_ENDPOINT is not a valid URL"

    return None


def _normalize_base_url(endpoint: str) -> str:
    # Foundry provides an OpenAI-compatible surface under /openai/v1
    # Example:
    #   https://recon-gpt.services.ai.azure.com/openai/v1
    return endpoint.rstrip("/")


def _normalize_foundry_base_url(endpoint: str) -> str:
    """Return a base_url suitable for OpenAI-compatible Foundry inference.

    Accepts either:
    - https://<project>.services.ai.azure.com
    - https://<project>.services.ai.azure.com/openai/v1
    and returns a URL ending in /openai/v1 exactly once.
    """

    base = _normalize_base_url(endpoint)
    if base.lower().endswith("/openai/v1"):
        return base
    return base + "/openai/v1"


def _normalize_azure_endpoint(endpoint: str) -> str:
    """Normalize Azure OpenAI resource endpoint.

    AzureOpenAI expects the *resource root* (no /openai or /openai/v1).
    Users sometimes paste endpoints that already include /openai/v1.
    """

    base = _normalize_base_url(endpoint)
    lowered = base.lower()
    for suffix in ("/openai/v1", "/openai"):
        if lowered.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/")


def _endpoint_kind(endpoint: str) -> str:
    """Best-effort classification to help choose correct endpoint/key."""
    host = urlparse(endpoint).netloc.lower()
    if host.endswith(".openai.azure.com"):
        return "azure_openai_resource"
    if host.endswith(".services.ai.azure.com"):
        return "foundry_project"
    if host.endswith(".cognitiveservices.azure.com"):
        return "azure_openai_legacy"
    return "unknown"


def _redact_transaction(txn: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(txn)
    for key in ["user_id", "upi_id", "ip_address", "device_id"]:
        if key in redacted and redacted[key] is not None:
            redacted[key] = "REDACTED"
    return redacted


def _build_client():
    """Create an OpenAI SDK client for Azure AI Foundry.

    We inject the API key via headers (api-key), not via query params.
    """

    _try_load_dotenv()
    endpoint = _env("AZURE_FOUNDRY_ENDPOINT")
    api_key = _env("AZURE_FOUNDRY_API_KEY")

    if not endpoint or not api_key:
        return None

    kind = _endpoint_kind(endpoint)

    # NOTE: We intentionally do NOT use chat.completions.
    # Azure OpenAI resources may appear under both *.openai.azure.com (new) and
    # *.cognitiveservices.azure.com (legacy). Both require api-version handling.
    if kind in {"azure_openai_resource", "azure_openai_legacy"}:
        from openai import AzureOpenAI  # type: ignore

        return AzureOpenAI(
            api_key=api_key,
            azure_endpoint=_normalize_azure_endpoint(endpoint),
            api_version=_AZURE_API_VERSION,
            timeout=8.0,
        )

    # Azure AI Foundry project endpoints expose an OpenAI-compatible surface under /openai/v1.
    # These typically use the `api-key` header.
    if kind == "foundry_project":
        from openai import OpenAI  # type: ignore

        base_url = _normalize_foundry_base_url(endpoint)
        return OpenAI(
            api_key="unused",
            base_url=base_url,
            default_headers={"api-key": api_key},
            timeout=8.0,
        )

    # Unknown endpoint type: fall back to OpenAI-compatible base URL (best effort).
    from openai import OpenAI  # type: ignore

    base_url = _normalize_foundry_base_url(endpoint)
    return OpenAI(
        api_key="unused",
        base_url=base_url,
        default_headers={"api-key": api_key},
        timeout=8.0,
    )


def _response_format_json_schema() -> Dict[str, Any]:
    # OpenAI Python SDK v2 uses `text={"format": ...}` for Structured Outputs.
    # This returns the *format object* (type=json_schema, name, schema, strict).
    return {
        "type": "json_schema",
        "name": "reconciliation_insight",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "root_cause": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
                "recommended_action": {"type": "string"},
            },
            "required": ["root_cause", "risk_level", "confidence_score", "recommended_action"],
        },
    }


def _classify_error(status_code: Optional[int]) -> str:
    if status_code == 401:
        return "AUTHENTICATION_MISCONFIG"
    if status_code == 404:
        return "DEPLOYMENT_MISMATCH"
    if status_code == 429:
        return "RATE_LIMITED"
    return "FOUNDRY_ERROR"


def _now() -> float:
    return time.time()


def _contract(
    *,
    enabled: bool,
    ok: bool,
    analysis: Optional[str],
    raw: Optional[object],
    status_code: Optional[int],
    error_code: Optional[str],
    error_type: Optional[str],
    hint: Optional[str],
) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "ok": ok,
        "analysis": analysis,
        "raw": raw,
        "status_code": status_code,
        "error_code": error_code,
        "error_type": error_type,
        "hint": hint,
        "generated_at": _now(),
    }


def _to_raw_dict(resp: Any) -> Dict[str, Any]:
    # The OpenAI SDK returns typed dict-like objects; prefer a plain JSON-serializable dict.
    try:
        if hasattr(resp, "model_dump"):
            return cast(Dict[str, Any], resp.model_dump())
    except Exception:
        pass

    try:
        if isinstance(resp, dict):
            return cast(Dict[str, Any], resp)
    except Exception:
        pass

    # Last resort: try __dict__ (may not be JSON-serializable)
    try:
        return cast(Dict[str, Any], dict(getattr(resp, "__dict__", {})))
    except Exception:
        return {}


def _extract_text_only_from_output(raw: Dict[str, Any]) -> str:
    """Extract text ONLY from response['output'][i]['content'][j]['text'].

    Any other shape is ignored by design.
    """

    output = raw.get("output")
    if not isinstance(output, list):
        return ""

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())

    return "\n".join(chunks).strip()


def _analysis_from_text(text: str) -> str:
    """Convert model text (ideally JSON) into a single compact analysis string."""

    # If the model returned strict JSON, turn it into a readable one-liner.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            root = parsed.get("root_cause")
            risk = parsed.get("risk_level")
            conf = parsed.get("confidence_score")
            action = parsed.get("recommended_action")
            if isinstance(root, str) and isinstance(risk, str) and action is not None:
                parts = [f"Root cause: {root}", f"Risk: {risk}"]
                if conf is not None:
                    parts.append(f"Confidence: {conf}")
                if isinstance(action, str):
                    parts.append(f"Action: {action}")
                return " | ".join(parts)
    except Exception:
        pass

    return text


def generate_reconciliation_insight(*, trace_id: str, primary_txn: Dict[str, Any], mismatch_context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an auditable reconciliation insight using Foundry Responses API.

    Returns a dict containing:
    - enabled/ok flags
    - the required structured fields: root_cause, risk_level, confidence_score, recommended_action
    - trace_id + timing metadata

    On any failure, returns enabled=True/ok=False with an error_code and continues safely.
    """

    config_error = _validate_config()
    if config_error:
        return _contract(
            enabled=False,
            ok=False,
            analysis=None,
            raw=None,
            status_code=None,
            error_code="NOT_CONFIGURED",
            error_type=None,
            hint=config_error,
        )

    deployment = _env("AZURE_FOUNDRY_DEPLOYMENT", _DEFAULT_DEPLOYMENT)
    if not deployment:
        return _contract(
            enabled=False,
            ok=False,
            analysis=None,
            raw=None,
            status_code=None,
            error_code="NOT_CONFIGURED",
            error_type=None,
            hint="Missing AZURE_FOUNDRY_DEPLOYMENT",
        )

    try:
        client = _build_client()
    except Exception:
        client = None

    if client is None:
        return _contract(
            enabled=False,
            ok=False,
            analysis=None,
            raw=None,
            status_code=None,
            error_code="FOUNDRY_CLIENT_INIT_FAILED",
            error_type=None,
            hint="Failed to initialize OpenAI client for Foundry",
        )

    system_text = (
        "You are a senior fintech reconciliation analyst. "
        "Return ONLY valid JSON matching the provided JSON Schema. "
        "Be concise, evidence-based, and enterprise-safe. "
        "Do not include PII."
    )

    user_payload = {
        "trace_id": trace_id,
        "transaction": _redact_transaction(primary_txn),
        "context": mismatch_context,
        "output_contract": {
            "root_cause": "string",
            "risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
            "confidence_score": "0..1",
            "recommended_action": "string",
        },
    }

    try:
        # Use Responses API with model set to the *deployment name*.
        request_payload: Any = {
            "model": deployment,
            "input": f"{system_text}\n\n{json.dumps(user_payload, ensure_ascii=False)}",
            "text": {"format": _response_format_json_schema()},
            "max_output_tokens": 800,
        }

        responses_client = cast(Any, client.responses)
        resp = responses_client.create(**request_payload)

        raw = _to_raw_dict(resp)
        extracted_text = (getattr(resp, "output_text", None) or "").strip()
        if not extracted_text:
            logger.warning("Foundry Responses returned no output text for trace_id=%s", trace_id)
            return _contract(
                enabled=True,
                ok=False,
                analysis=None,
                raw=raw or None,
                status_code=None,
                error_code="EMPTY_OUTPUT",
                error_type="EmptyOutput",
                hint="No output_text returned from Responses API",
            )

        analysis_text = _analysis_from_text(extracted_text)
        return _contract(
            enabled=True,
            ok=True,
            analysis=analysis_text,
            raw=raw or None,
            status_code=None,
            error_code=None,
            error_type=None,
            hint=None,
        )

    except Exception as e:
        status_code = getattr(e, "status_code", None)
        error_type = type(e).__name__
        error_code = _classify_error(status_code)

        endpoint = _env("AZURE_FOUNDRY_ENDPOINT") or ""
        kind = _endpoint_kind(endpoint) if endpoint else "unknown"
        hint: Optional[str] = None
        if status_code == 404:
            if kind == "azure_openai_resource":
                hint = (
                    "404 Not Found. Most common causes: wrong deployment name or deployment not created in the Azure OpenAI resource. "
                    "Go to Azure OpenAI Studio -> Deployments and copy the deployment name exactly."
                )
            elif kind == "foundry_project":
                hint = (
                    "404 Not Found. This endpoint looks like a Foundry project endpoint (.services.ai.azure.com). "
                    "Ensure the deployment exists in that Foundry project, and that you're using the project's inference key (not an Azure OpenAI resource key)."
                )
            else:
                hint = (
                    "404 Not Found. Could be wrong endpoint type or wrong deployment name. "
                    "If your endpoint is an Azure OpenAI resource, it should look like https://<name>.openai.azure.com. "
                    "If it's a Foundry project endpoint, it usually ends with .services.ai.azure.com."
                )
        elif status_code == 401:
            if kind == "azure_openai_resource":
                hint = "401 Unauthorized. Use the Azure OpenAI resource key from 'Keys and Endpoint' for https://<name>.openai.azure.com."
            elif kind == "foundry_project":
                hint = "401 Unauthorized. Use the Foundry project inference key for the .services.ai.azure.com endpoint (not an Azure OpenAI resource key)."
            else:
                hint = "401 Unauthorized. The key does not match the endpoint you're calling."
        elif status_code == 429:
            hint = "Rate limited. Reduce traffic or add retry/backoff at the call site if needed."

        # Never leak exceptions; always return the contract.
        return _contract(
            enabled=True,
            ok=False,
            analysis=None,
            raw=None,
            status_code=cast(Optional[int], status_code),
            error_code=error_code,
            error_type=error_type,
            hint=hint,
        )


_PROBE_CACHE: Dict[str, Any] = {"at": None, "value": None}


def probe_foundry_status(ttl_seconds: int = 30) -> Dict[str, Any]:
    """Lightweight, cached probe for auth + deployment existence.

    - Uses a minimal Responses API call.
    - Cached for 30s by default.
    """

    now = _now()
    last_at = _PROBE_CACHE.get("at")
    if isinstance(last_at, (int, float)) and (now - last_at) < ttl_seconds and _PROBE_CACHE.get("value"):
        return cast(Dict[str, Any], _PROBE_CACHE["value"])

    start = time.time()
    config_error = _validate_config()
    if config_error:
        result = {
            "ok": False,
            "configured": False,
            "error_code": "NOT_CONFIGURED",
            "status_code": None,
            "error_type": None,
            "hint": config_error,
            "latency_ms": 0,
            "generated_at": now,
        }
        _PROBE_CACHE["at"] = now
        _PROBE_CACHE["value"] = result
        return result

    deployment = _env("AZURE_FOUNDRY_DEPLOYMENT", _DEFAULT_DEPLOYMENT)
    client = _build_client()
    if not deployment or client is None:
        result = {
            "ok": False,
            "configured": False,
            "error_code": "FOUNDRY_CLIENT_INIT_FAILED",
            "status_code": None,
            "error_type": None,
            "hint": "Failed to initialize Foundry client",
            "latency_ms": int((time.time() - start) * 1000),
            "generated_at": now,
        }
        _PROBE_CACHE["at"] = now
        _PROBE_CACHE["value"] = result
        return result

    try:
        request_payload: Any = {
            "model": deployment,
            "input": "Return the JSON object with root_cause='OK'.",
            "max_output_tokens": 256,
        }

        responses_client = cast(Any, client.responses)
        resp = responses_client.create(**request_payload)
        raw = _to_raw_dict(resp)
        extracted_text = (getattr(resp, "output_text", None) or "").strip()
        ok = bool(extracted_text)
        hint: Optional[str] = None
        if not ok:
            incomplete_details = None
            if isinstance(raw, dict):
                incomplete_details = raw.get("incomplete_details")
            if isinstance(incomplete_details, dict) and incomplete_details.get("reason") == "max_output_tokens":
                hint = "Model produced no text before hitting max_output_tokens; increase max_output_tokens for probe."
            else:
                hint = "No output_text returned from Responses API"

        result = {
            "ok": ok,
            "configured": True,
            "error_code": None if ok else "EMPTY_OUTPUT",
            "status_code": None,
            "error_type": None if ok else "EmptyOutput",
            "hint": None if ok else hint,
            "latency_ms": int((time.time() - start) * 1000),
            "generated_at": now,
        }
    except Exception as e:
        status_code = getattr(e, "status_code", None)
        code = _classify_error(status_code)
        hint: Optional[str] = None
        body = getattr(e, "body", None)
        if status_code == 400 and isinstance(body, dict):
            message = body.get("message")
            param = body.get("param")
            if isinstance(message, str) and message.strip():
                hint = message.strip()
                if isinstance(param, str) and param.strip():
                    hint = f"{hint} (param: {param})"

        if status_code == 404:
            hint = "Deployment not found. Ensure AZURE_FOUNDRY_DEPLOYMENT matches an existing deployment name in Foundry."
        elif status_code == 401:
            hint = "Unauthorized. Check AZURE_FOUNDRY_API_KEY and access to the Foundry endpoint."
        elif status_code == 429:
            hint = "Rate limited. Reduce traffic or add retry/backoff."
        result = {
            "ok": False,
            "configured": True,
            "error_code": code,
            "status_code": status_code,
            "error_type": type(e).__name__,
            "hint": hint,
            "latency_ms": int((time.time() - start) * 1000),
            "generated_at": now,
        }

    _PROBE_CACHE["at"] = now
    _PROBE_CACHE["value"] = result
    return result
