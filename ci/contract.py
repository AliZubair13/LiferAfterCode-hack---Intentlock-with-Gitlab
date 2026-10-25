"""Intent contract: parse and validate.

The Intent Agent posts the contract as a fenced ```yaml block in an issue
comment. This module turns that text into a validated dict. It is plain
Python on purpose: no LLM is involved in deciding what the contract says.
"""
import re

import yaml

RISK_CLASSES = ("low", "medium", "high")
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


def validate_contract(contract: dict) -> dict:
    if "issue" not in contract:
        raise ContractError("missing required field: issue")

    risk = str(contract.get("risk_class", "low")).lower()
    if risk not in RISK_CLASSES:
        raise ContractError(f"risk_class must be one of {RISK_CLASSES}")

    max_deps = contract.get("max_new_dependencies", 0)
    if not isinstance(max_deps, int) or isinstance(max_deps, bool) or max_deps < 0:
        raise ContractError("max_new_dependencies must be a non-negative integer")

    return {
        "issue": contract["issue"],
        "summary": str(contract.get("summary", "")),
        "allowed_paths": _str_list(contract, "allowed_paths", required=True),
        "forbidden_paths": _str_list(contract, "forbidden_paths", required=False),
        "acceptance_criteria": _str_list(contract, "acceptance_criteria", required=True),
        "max_new_dependencies": max_deps,
        "risk_class": risk,
    }
