"""Explicit, provider-neutral HTTP JSON fallback for uncertain extraction.

The parser never constructs this client implicitly.  Callers must supply a
configured :class:`HTTPJSONLLMFallback`, which keeps the normal extraction
path deterministic and offline.  The transport is injectable so tests can
exercise the interface without making network calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union


JSONMapping = Mapping[str, Any]
TransportResponse = Union[
    Mapping[str, Any],
    bytes,
    str,
    Tuple[int, Union[Mapping[str, Any], bytes, str], Mapping[str, str]],
]
Transport = Callable[[urllib.request.Request, float], TransportResponse]


class LLMFallbackError(RuntimeError):
    """Base error raised by the HTTP JSON fallback."""


class LLMFallbackNotConfigured(LLMFallbackError):
    """Raised when a caller tries to use an unconfigured fallback."""


class LLMFallbackResponseError(LLMFallbackError):
    """Raised when an endpoint response cannot be validated as JSON fields."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so credentials can never cross origin or downgrade."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant is forbidden: %s" % value)


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    """Return a finite confidence in ``[0, 1]`` without guessing from prose."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number or number in (float("inf"), float("-inf")):
        number = default
    return round(max(0.0, min(1.0, number)), 6)


@dataclass(frozen=True)
class LLMFallbackConfig:
    """Configuration required before any HTTP request is permitted.

    ``endpoint`` and ``model`` must both be non-empty.  HTTPS is required by
    default; ``allow_insecure_http`` exists only for explicit local/testing
    endpoints.  Environment access is limited to the optional, explicitly
    named ``api_key_env`` variable.
    """

    endpoint: str = ""
    model: str = ""
    api_key: Optional[str] = field(default=None, repr=False)
    api_key_env: Optional[str] = None
    timeout_seconds: float = 30.0
    max_input_chars: int = 12000
    max_request_bytes: int = 256000
    max_response_bytes: int = 1000000
    max_json_depth: int = 20
    max_fields: int = 64
    max_field_value_chars: int = 4000
    max_locator_chars: int = 500
    max_warnings: int = 50
    max_warning_chars: int = 500
    extra_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    allow_insecure_http: bool = False

    @property
    def configured(self) -> bool:
        """Whether the minimum explicit configuration is present."""

        return bool(
            isinstance(self.endpoint, str)
            and isinstance(self.model, str)
            and self.endpoint.strip()
            and self.model.strip()
        )

    def validate(self) -> None:
        """Validate configuration immediately before building a request."""

        if not self.configured:
            raise LLMFallbackNotConfigured(
                "LLM fallback requires explicit endpoint and model configuration"
            )
        parsed = urllib.parse.urlparse(self.endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LLMFallbackNotConfigured(
                "LLM fallback endpoint must be an HTTP(S) URL"
            )
        if parsed.scheme != "https" and not self.allow_insecure_http:
            raise LLMFallbackNotConfigured(
                "LLM fallback requires HTTPS unless allow_insecure_http is explicitly true"
            )
        if self.timeout_seconds <= 0:
            raise LLMFallbackNotConfigured("timeout_seconds must be positive")
        if self.max_input_chars <= 0:
            raise LLMFallbackNotConfigured("max_input_chars must be positive")
        for name in (
            "max_request_bytes",
            "max_response_bytes",
            "max_json_depth",
            "max_fields",
            "max_field_value_chars",
            "max_locator_chars",
            "max_warnings",
            "max_warning_chars",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise LLMFallbackNotConfigured("%s must be a positive integer" % name)


@dataclass(frozen=True)
class LLMExtractedField:
    """One field returned by the fallback with its claimed source locator."""

    value: Any
    locator: str = "document"
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        """Return a compact JSON-serializable representation."""

        return {
            "value": self.value,
            "locator": self.locator,
            "confidence": _clamp_confidence(self.confidence),
        }


@dataclass
class LLMFallbackResult:
    """Validated result returned by :meth:`HTTPJSONLLMFallback.extract`."""

    fields: Dict[str, LLMExtractedField]
    confidence: float
    model: str
    request_sha256: str
    response_sha256: str
    request_id: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a compact JSON-serializable representation."""

        payload: Dict[str, Any] = {
            "model": self.model,
            "confidence": _clamp_confidence(self.confidence),
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "fields": {
                name: item.to_dict() for name, item in sorted(self.fields.items())
            },
        }
        if self.request_id:
            payload["request_id"] = self.request_id
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


class HTTPJSONLLMFallback:
    """Post a compact extraction request to an explicitly configured endpoint.

    The endpoint contract is intentionally small.  Requests contain ``task``,
    ``model``, ``document``, ``known_fields`` and ``response_schema``.  A
    response may return ``fields`` directly or wrap the same JSON object in a
    common ``choices[0].message.content``/``output_text`` envelope.
    """

    def __init__(
        self,
        config: Optional[LLMFallbackConfig] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        self.config = config or LLMFallbackConfig()
        self._transport = transport or self._default_transport

    @property
    def configured(self) -> bool:
        """Whether this client can be invoked."""

        return self.config.configured

    def build_payload(
        self,
        *,
        text: str,
        source_sha256: str,
        existing_fields: Optional[Mapping[str, Any]] = None,
        requested_fields: Optional[Sequence[str]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Build the documented JSON request without sending it."""

        self.config.validate()
        warnings: List[str] = []
        excerpt = text
        if len(excerpt) > self.config.max_input_chars:
            excerpt = excerpt[: self.config.max_input_chars]
            warnings.append("llm_input_truncated")

        payload: Dict[str, Any] = {
            "task": "extract_leveraged_life_product_fields",
            "prompt_version": "llpi-extract-1.0.0",
            "model": self.config.model,
            "document": {
                "sha256": source_sha256,
                "text": excerpt,
            },
            "known_fields": dict(existing_fields or {}),
            "requested_fields": list(requested_fields or []),
            "response_schema": {
                "type": "object",
                "required": ["fields"],
                "fields": {
                    "<field_name>": {
                        "value": "json value",
                        "locator": "page/section/table locator",
                        "confidence": "number from 0 to 1",
                    }
                },
            },
        }
        if context:
            payload["context"] = dict(context)
        if len(payload["requested_fields"]) > self.config.max_fields:
            raise LLMFallbackNotConfigured(
                "requested_fields exceeds configured max_fields"
            )
        return payload, warnings

    def extract(
        self,
        *,
        text: str,
        source_sha256: str,
        existing_fields: Optional[Mapping[str, Any]] = None,
        requested_fields: Optional[Sequence[str]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> LLMFallbackResult:
        """Send one HTTP JSON request and validate the returned fields.

        This is the only method that may perform network I/O.  It refuses to
        run unless the supplied configuration is complete.
        """

        payload, warnings = self.build_payload(
            text=text,
            source_sha256=source_sha256,
            existing_fields=existing_fields,
            requested_fields=requested_fields,
            context=context,
        )
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise LLMFallbackNotConfigured(
                "LLM fallback request must contain finite bounded JSON"
            ) from exc
        if len(body) > self.config.max_request_bytes:
            raise LLMFallbackNotConfigured(
                "LLM fallback request exceeds configured byte limit"
            )
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "leveraged-life-product-intelligence/1.0.0",
        }
        headers.update(
            {str(key): str(value) for key, value in self.config.extra_headers.items()}
        )
        api_key = self.config.api_key
        if api_key is None and self.config.api_key_env:
            api_key = os.environ.get(self.config.api_key_env)
        if api_key:
            headers.setdefault("Authorization", "Bearer %s" % api_key)

        request = urllib.request.Request(
            self.config.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            transported = self._transport(request, float(self.config.timeout_seconds))
        except urllib.error.HTTPError as exc:
            raise LLMFallbackError("LLM fallback HTTP error: %s" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise LLMFallbackError(
                "LLM fallback connection error: %s" % exc.reason
            ) from exc
        except TimeoutError as exc:
            raise LLMFallbackError("LLM fallback request timed out") from exc

        status, response_payload, response_headers = self._normalize_transport_response(
            transported
        )
        if status < 200 or status >= 300:
            raise LLMFallbackError("LLM fallback returned HTTP status %s" % status)

        decoded = self._decode_json_payload(
            response_payload,
            self.config.max_response_bytes,
            self.config.max_json_depth,
        )
        normalized = self._unwrap_response(decoded)
        self._enforce_json_depth(normalized, self.config.max_json_depth)
        fields = self._normalize_fields(
            normalized.get("fields"),
            max_fields=self.config.max_fields,
            max_value_chars=self.config.max_field_value_chars,
            max_locator_chars=self.config.max_locator_chars,
        )
        requested = {str(name) for name in (requested_fields or [])}
        if requested:
            unexpected = sorted(set(fields) - requested)
            if unexpected:
                warnings.append(
                    "llm_unrequested_fields_dropped:%s" % ",".join(unexpected)
                )
            fields = {
                name: value for name, value in fields.items() if name in requested
            }
        if not fields:
            raise LLMFallbackResponseError(
                "LLM fallback response contains no valid fields"
            )

        overall = normalized.get("confidence")
        if overall is None:
            overall = sum(item.confidence for item in fields.values()) / float(
                len(fields)
            )
        request_id = self._request_id(decoded, response_headers)
        response_warnings = normalized.get("warnings")
        if isinstance(response_warnings, list):
            selected_warnings = response_warnings[: self.config.max_warnings]
            warnings.extend(
                str(item)[: self.config.max_warning_chars] for item in selected_warnings
            )
            if len(response_warnings) > self.config.max_warnings:
                warnings.append("llm_response_warnings_truncated")
        return LLMFallbackResult(
            fields=fields,
            confidence=_clamp_confidence(overall),
            model=self.config.model,
            request_sha256=hashlib.sha256(body).hexdigest(),
            response_sha256=self._response_sha256(response_payload),
            request_id=request_id,
            warnings=warnings,
        )

    def _default_transport(
        self,
        request: urllib.request.Request,
        timeout: float,
    ) -> TransportResponse:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            response_headers = {
                str(key): str(value) for key, value in response.headers.items()
            }
            content_length = response_headers.get(
                "Content-Length"
            ) or response_headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > self.config.max_response_bytes:
                        raise LLMFallbackResponseError(
                            "LLM fallback response exceeds configured byte limit"
                        )
                except ValueError:
                    pass
            body = response.read(self.config.max_response_bytes + 1)
            if len(body) > self.config.max_response_bytes:
                raise LLMFallbackResponseError(
                    "LLM fallback response exceeds configured byte limit"
                )
            return status, body, response_headers

    @staticmethod
    def _normalize_transport_response(
        response: TransportResponse,
    ) -> Tuple[int, Union[Mapping[str, Any], bytes, str], Mapping[str, str]]:
        if isinstance(response, tuple):
            if len(response) != 3:
                raise LLMFallbackResponseError(
                    "transport tuple must be (status, body, headers)"
                )
            status, body, headers = response
            return int(status), body, dict(headers)
        return 200, response, {}

    @staticmethod
    def _decode_json_payload(
        payload: Union[Mapping[str, Any], bytes, str],
        max_response_bytes: int,
        max_json_depth: int,
    ) -> Dict[str, Any]:
        if isinstance(payload, Mapping):
            decoded_mapping = dict(payload)
            try:
                encoded = json.dumps(
                    decoded_mapping,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, RecursionError) as exc:
                raise LLMFallbackResponseError(
                    "LLM fallback response must contain finite JSON values"
                ) from exc
            if len(encoded) > max_response_bytes:
                raise LLMFallbackResponseError(
                    "LLM fallback response exceeds configured byte limit"
                )
            HTTPJSONLLMFallback._enforce_json_depth(decoded_mapping, max_json_depth)
            return decoded_mapping
        if isinstance(payload, bytes):
            if len(payload) > max_response_bytes:
                raise LLMFallbackResponseError(
                    "LLM fallback response exceeds configured byte limit"
                )
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LLMFallbackResponseError(
                    "LLM fallback response is not UTF-8"
                ) from exc
        if not isinstance(payload, str):
            raise LLMFallbackResponseError("LLM fallback response must be JSON")
        if len(payload.encode("utf-8")) > max_response_bytes:
            raise LLMFallbackResponseError(
                "LLM fallback response exceeds configured byte limit"
            )
        try:
            decoded = json.loads(payload, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise LLMFallbackResponseError(
                "LLM fallback response is not valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise LLMFallbackResponseError(
                "LLM fallback response root must be an object"
            )
        HTTPJSONLLMFallback._enforce_json_depth(decoded, max_json_depth)
        return decoded

    @staticmethod
    def _enforce_json_depth(value: Any, max_depth: int) -> None:
        stack: List[Tuple[Any, int]] = [(value, 1)]
        while stack:
            current, depth = stack.pop()
            if depth > max_depth:
                raise LLMFallbackResponseError(
                    "LLM fallback response exceeds configured JSON depth"
                )
            if isinstance(current, Mapping):
                stack.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                stack.extend((item, depth + 1) for item in current)

    @staticmethod
    def _response_sha256(payload: Union[Mapping[str, Any], bytes, str]) -> str:
        if isinstance(payload, Mapping):
            raw = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        elif isinstance(payload, bytes):
            raw = payload
        else:
            raw = str(payload).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _unwrap_response(cls, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if isinstance(payload.get("fields"), (dict, list)):
            return dict(payload)

        candidate: Any = payload.get("output_text")
        if candidate is None:
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, Mapping):
                    message = first.get("message")
                    if isinstance(message, Mapping):
                        candidate = message.get("content")
                    if candidate is None:
                        candidate = first.get("text")
        if candidate is None:
            candidate = cls._content_from_responses_envelope(payload.get("output"))
        if isinstance(candidate, Mapping):
            return dict(candidate)
        if isinstance(candidate, str):
            candidate = cls._strip_json_fence(candidate)
            try:
                decoded = json.loads(candidate, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError, RecursionError) as exc:
                raise LLMFallbackResponseError(
                    "LLM fallback content does not contain a JSON object"
                ) from exc
            if isinstance(decoded, dict):
                return decoded
        raise LLMFallbackResponseError("LLM fallback response does not expose fields")

    @staticmethod
    def _content_from_responses_envelope(output: Any) -> Optional[Any]:
        if not isinstance(output, list):
            return None
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, Mapping):
                    if part.get("text") is not None:
                        return part.get("text")
                    if part.get("json") is not None:
                        return part.get("json")
        return None

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        stripped = text.strip()
        match = re.match(
            r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE
        )
        return match.group(1).strip() if match else stripped

    @staticmethod
    def _normalize_fields(
        raw_fields: Any,
        *,
        max_fields: int,
        max_value_chars: int,
        max_locator_chars: int,
    ) -> Dict[str, LLMExtractedField]:
        items: List[Tuple[str, Any]] = []
        if isinstance(raw_fields, Mapping):
            items = [(str(name), value) for name, value in raw_fields.items()]
        elif isinstance(raw_fields, list):
            for item in raw_fields:
                if isinstance(item, Mapping) and item.get("name"):
                    items.append((str(item["name"]), item))
        if len(items) > max_fields:
            raise LLMFallbackResponseError(
                "LLM fallback response exceeds configured field limit"
            )

        normalized: Dict[str, LLMExtractedField] = {}
        for name, raw in items:
            clean_name = name.strip()
            if not clean_name or len(clean_name) > 200:
                continue
            if isinstance(raw, Mapping) and "value" in raw:
                value = raw.get("value")
                locator = str(raw.get("locator") or "document")[:max_locator_chars]
                confidence = _clamp_confidence(raw.get("confidence"), 0.5)
            else:
                value = raw
                locator = "document"
                confidence = 0.5
            try:
                encoded_value = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise LLMFallbackResponseError(
                    "LLM fallback field %s is not finite JSON" % clean_name
                ) from exc
            if len(encoded_value) > max_value_chars:
                raise LLMFallbackResponseError(
                    "LLM fallback field %s exceeds configured value limit" % clean_name
                )
            normalized[clean_name] = LLMExtractedField(
                value=value,
                locator=locator,
                confidence=confidence,
            )
        return normalized

    @staticmethod
    def _request_id(
        payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> Optional[str]:
        direct = payload.get("request_id") or payload.get("id")
        if direct is not None:
            return str(direct)
        lowered = {str(key).lower(): value for key, value in headers.items()}
        header_value = lowered.get("x-request-id") or lowered.get("request-id")
        return str(header_value) if header_value else None


__all__ = [
    "HTTPJSONLLMFallback",
    "LLMExtractedField",
    "LLMFallbackConfig",
    "LLMFallbackError",
    "LLMFallbackNotConfigured",
    "LLMFallbackResponseError",
    "LLMFallbackResult",
]
