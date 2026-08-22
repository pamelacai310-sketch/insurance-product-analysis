"""Deterministic leveraged-life product intelligence engine."""

from .llm_fallback import (
    HTTPJSONLLMFallback,
    LLMExtractedField,
    LLMFallbackConfig,
    LLMFallbackError,
    LLMFallbackNotConfigured,
    LLMFallbackResponseError,
    LLMFallbackResult,
)
from .parsers import (
    ConfidenceRouter,
    Evidence,
    ExtractedField,
    ExtractionError,
    ExtractionResult,
    FileRouter,
    PageExtraction,
    RouteDecision,
    TableExtraction,
    UnsupportedFileTypeError,
    extract_file,
    parse_file,
    sha256_file,
)

__version__ = "1.0.0"

__all__ = [
    "ConfidenceRouter",
    "Evidence",
    "ExtractedField",
    "ExtractionError",
    "ExtractionResult",
    "FileRouter",
    "HTTPJSONLLMFallback",
    "LLMExtractedField",
    "LLMFallbackConfig",
    "LLMFallbackError",
    "LLMFallbackNotConfigured",
    "LLMFallbackResponseError",
    "LLMFallbackResult",
    "PageExtraction",
    "RouteDecision",
    "TableExtraction",
    "UnsupportedFileTypeError",
    "extract_file",
    "parse_file",
    "sha256_file",
]
