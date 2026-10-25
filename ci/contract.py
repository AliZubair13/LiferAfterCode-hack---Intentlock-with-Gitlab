"""Intent contract: parse and validate.

The Intent Agent posts the contract as a fenced ```yaml block in an issue
comment. This module turns that text into a validated dict. It is plain
Python on purpose: no LLM is involved in deciding what a contract may say.

Because an LLM writes the contract from untrusted issue text, validation is
strict: a poisoned contract that tries to allow everything is rejected here.
"""
import re

import yaml

from ci.paths import WILDCARD_CHARS, overlaps_protected

RISK_CLASSES = ("low", "medium", "high")
MAX_ALLOWED_PATHS = 10
MAX_NEW_DEPENDENCIES = 3
FENCE_RE = re.compile(r"```(?:ya?ml)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class ContractError(ValueError):
    """Raised when no valid contract can be extracted."""


def _candidate_blocks(text: str):
    blocks = FENCE_RE.findall(text)
    # Also accept a bare YAML document (no fence).
    blocks.append(text)
    return blocks


def parse_contract(text: str) -> dict:
    """Extract and validate the first intent_contract in `text`."""
    for block in _candidate_blocks(text):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and isinstance(data.get("intent_contract"), dict):
            return validate_contract(data["intent_contract"])
    raise ContractError("no intent_contract block found")


def _str_list(contract: dict, key: str, required: bool) -> list:
    value = contract.get(key)
    if value is None:
        if required:
            raise ContractError(f"missing required field: {key}")
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ContractError(f"{key} must be a list of strings")
    if required and not value:
        raise ContractError(f"{key} must not be empty")
    return value


def _check_allowed_path(path: str) -> None:
    if not path or path != path.strip():
        raise ContractError(f"allowed path {path!r} is empty or has stray whitespace")
    if path.startswith("/") or ".." in path.split("/"):
        raise ContractError(f"allowed path {path!r} must be a relative path inside the repo")
    if path.endswith("/"):
        raise ContractError(f"allowed path {path!r} is a directory; list exact files instead")
    segments = path.split("/")
    if any(ch in seg for seg in segments[:-1] for ch in WILDCARD_CHARS):
        raise ContractError(f"allowed path {path!r} has a wildcard in a directory name")
    if segments[-1] in ("*", "**", "*.*"):
        raise ContractError(f"allowed path {path!r} is a catch-all pattern")
    if overlaps_protected(path):
        raise ContractError(f"allowed path {path!r} covers a protected path (CI config or gates)")


def validate_contract(contract: dict) -> dict:
    if "issue" not in contract:
        raise ContractError("missing required field: issue")

    risk = str(contract.get("risk_class", "low")).lower()
    if risk not in RISK_CLASSES:
        raise ContractError(f"risk_class must be one of {RISK_CLASSES}")

    max_deps = contract.get("max_new_dependencies", 0)
    if not isinstance(max_deps, int) or isinstance(max_deps, bool) or max_deps < 0:
        raise ContractError("max_new_dependencies must be a non-negative integer")
    if max_deps > MAX_NEW_DEPENDENCIES:
        raise ContractError(f"max_new_dependencies may not exceed {MAX_NEW_DEPENDENCIES}")

    allowed = _str_list(contract, "allowed_paths", required=True)
    if len(allowed) > MAX_ALLOWED_PATHS:
        raise ContractError(f"too many allowed_paths ({len(allowed)} > {MAX_ALLOWED_PATHS})")
    for path in allowed:
        _check_allowed_path(path)

    return {
        "issue": contract["issue"],
        "summary": str(contract.get("summary", "")),
        "allowed_paths": allowed,
        "forbidden_paths": _str_list(contract, "forbidden_paths", required=False),
        "acceptance_criteria": _str_list(contract, "acceptance_criteria", required=True),
        "max_new_dependencies": max_deps,
        "risk_class": risk,
    }
