from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping

from .common import SCHEMA_VERSION, ValidationError, deep_copy_json


ALLOWED_TARGETS = (
    re.compile(r"^/configurations/\d+/death_benefit(?:/rule)?$"),
    re.compile(r"^/configurations/\d+/annuity_rules/\d+$"),
    re.compile(
        r"^/configurations/\d+/dimensions/(?:guarantee_option|premium_mode|product_option_code)$"
    ),
)


def _pointer_tokens(pointer: str) -> List[str]:
    if not pointer.startswith("/"):
        raise ValidationError(["resolution target_path must be a JSON Pointer"])
    return [
        token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")
    ]


def _set_pointer(document: Any, pointer: str, value: Any) -> None:
    tokens = _pointer_tokens(pointer)
    current = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ValidationError([f"resolution path does not exist: {pointer}"])
            current = current[int(token)]
        elif isinstance(current, dict):
            if token not in current:
                raise ValidationError([f"resolution path does not exist: {pointer}"])
            current = current[token]
        else:
            raise ValidationError([f"resolution path is not traversable: {pointer}"])
    last = tokens[-1]
    if isinstance(current, list):
        if not last.isdigit() or int(last) >= len(current):
            raise ValidationError([f"resolution list index is invalid: {pointer}"])
        current[int(last)] = value
    elif isinstance(current, dict):
        current[last] = value
    else:
        raise ValidationError([f"resolution target is not writable: {pointer}"])


def _numeric_tokens(value: Any) -> List[str]:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.findall(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?", rendered)


def apply_resolutions(
    draft: Dict[str, Any], review_queue: Mapping[str, Any], patch: Mapping[str, Any]
) -> Dict[str, Any]:
    unknown_top_level = set(patch) - {"schema_version", "resolutions"}
    if unknown_top_level:
        raise ValidationError(
            [
                f"resolution patch contains unsupported fields: {sorted(unknown_top_level)}"
            ]
        )
    if patch.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(
            [f"resolution patch schema_version must equal {SCHEMA_VERSION}"]
        )
    resolutions = patch.get("resolutions")
    if not isinstance(resolutions, list) or not resolutions:
        raise ValidationError(
            ["resolution patch must contain a non-empty resolutions list"]
        )
    tasks = {
        item.get("id"): item
        for item in review_queue.get("items", [])
        if item.get("route") == "llm_semantic_resolution"
    }
    output = deep_copy_json(draft)
    seen = set()
    for index, resolution in enumerate(resolutions):
        path = f"$.resolutions[{index}]"
        if not isinstance(resolution, Mapping):
            raise ValidationError([f"{path} must be an object"])
        allowed = {
            "task_id",
            "target_path",
            "value",
            "source_record_id",
            "candidate_confidence",
            "rationale",
        }
        unknown = set(resolution) - allowed
        if unknown:
            raise ValidationError(
                [f"{path} contains unsupported fields: {sorted(unknown)}"]
            )
        missing = allowed - set(resolution)
        if missing:
            raise ValidationError(
                [f"{path} is missing required fields: {sorted(missing)}"]
            )
        if (
            not isinstance(resolution.get("rationale"), str)
            or not resolution.get("rationale", "").strip()
        ):
            raise ValidationError([f"{path}.rationale must be a non-empty string"])
        task_id = resolution.get("task_id")
        if task_id in seen:
            raise ValidationError([f"{path}.task_id is duplicated"])
        seen.add(task_id)
        task = tasks.get(task_id)
        if task is None:
            raise ValidationError(
                [f"{path}.task_id is not an unresolved semantic task"]
            )
        if resolution.get("source_record_id") != task.get("record_id"):
            raise ValidationError(
                [f"{path}.source_record_id must match the review evidence record"]
            )
        if resolution.get("candidate_confidence") != "medium":
            raise ValidationError(
                [
                    f"{path}.candidate_confidence must be medium; LLM resolutions cannot be high confidence"
                ]
            )
        target = resolution.get("target_path")
        if not isinstance(target, str) or not any(
            pattern.fullmatch(target) for pattern in ALLOWED_TARGETS
        ):
            raise ValidationError(
                [f"{path}.target_path is outside the semantic resolution allowlist"]
            )
        snippet = str(task.get("snippet", ""))
        snippet_numbers = set(re.findall(r"-?\d+(?:\.\d+)?", snippet.replace(",", "")))
        unanchored = [
            token
            for token in _numeric_tokens(resolution.get("value"))
            if token not in snippet_numbers
        ]
        if unanchored:
            raise ValidationError(
                [
                    f"{path}.value contains numeric tokens not anchored in the evidence snippet: {sorted(set(unanchored))}"
                ]
            )
        _set_pointer(output, target, deep_copy_json(resolution.get("value")))
    resolved_record_ids = {
        tasks[task_id].get("record_id") for task_id in seen if task_id in tasks
    }
    remaining_record_ids = {
        item.get("record_id")
        for item in review_queue.get("items", [])
        if item.get("route") == "llm_semantic_resolution" and item.get("id") not in seen
    }
    for evidence in output.get("evidence", []):
        if (
            isinstance(evidence, dict)
            and evidence.get("evidence_id")
            in resolved_record_ids - remaining_record_ids
            and evidence.get("status") == "unresolved"
        ):
            evidence["status"] = "resolved"
    return output
