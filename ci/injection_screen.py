"""Injection screen: deterministic first pass over issue text.

Rules decide. Any HIGH finding blocks the issue before an agent ever sees it.
MEDIUM findings are reported as warnings (an LLM classifier can review them
later; its verdict stays advisory and can never lift a HIGH block).

Usage:
    python -m ci.injection_screen --file issue.txt
Exit code 0 = PASS or REVIEW, 1 = BLOCK.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict

HIGH, MEDIUM = "high", "medium"

RULES = [
    ("override_instructions", HIGH,
     r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+"
     r"(?:instructions?|rules?|prompts?|guidelines?)"),
    ("disregard_instructions", HIGH,
     r"(?:disregard|forget|override)\s+(?:all\s+|any\s+|your\s+|the\s+)?"
     r"(?:previous\s+|prior\s+)?(?:instructions?|rules?|guidelines?|safeguards?)"),
    ("fake_authority", HIGH,
     r"\b(?:system|admin(?:istrator)?|maintainer|security\s+team)\s+"
     r"(?:override|message|notice|instruction|directive)\b"),
    ("secret_reference", HIGH,
     r"\bCI_[A-Z_]*(?:TOKEN|PASSWORD|KEY|SECRET)[A-Z_]*\b|\bGITLAB_TOKEN\b|"
     r"\bGOOGLE_APPLICATION_CREDENTIALS\b|\bAWS_SECRET[A-Z_]*\b"),
    ("disable_checks", HIGH,
     r"(?:disable|skip|bypass|turn\s+off|remove)\s+(?:the\s+|all\s+)?"
     r"(?:security\s+)?(?:scans?|scanners?|tests?|checks?|pipeline|review)\b"),
    ("hidden_unicode", HIGH,
     "[​-‏‪-‮⁠-⁤﻿]"),
    ("ci_config_mention", MEDIUM, r"\.gitlab-ci\.ya?ml|\ballow_failure\b|--no-verify"),
    ("html_comment", MEDIUM, r"<!--.*?-->"),
    ("encoded_blob", MEDIUM, r"[A-Za-z0-9+/]{60,}={0,2}"),
    ("role_markers", MEDIUM,
     r"<\|?(?:system|im_start|assistant)\|?>|^\s*(?:system|assistant)\s*:"),
]

COMPILED = [
    (name, sev, re.compile(pat, re.IGNORECASE | re.DOTALL | re.MULTILINE))
    for name, sev, pat in RULES
]


@dataclass
class Finding:
    rule: str
    severity: str
    excerpt: str


def screen(text: str):
    """Return (verdict, findings). verdict is BLOCK, REVIEW or PASS."""
    findings = []
    for name, sev, rx in COMPILED:
        m = rx.search(text)
        if m:
            excerpt = m.group(0)[:60]
            if name == "hidden_unicode":
                excerpt = f"U+{ord(m.group(0)[0]):04X}"
            findings.append(Finding(name, sev, excerpt))
    if any(f.severity == HIGH for f in findings):
        return "BLOCK", findings
    if findings:
        return "REVIEW", findings
    return "PASS", findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="file containing the issue text")
    ap.add_argument("--report", default="injection_report.json")
    args = ap.parse_args(argv)

    with open(args.file, encoding="utf-8") as fh:
        verdict, findings = screen(fh.read())

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "findings": [asdict(f) for f in findings]}, fh, indent=2)

    print(f"INJECTION-SCREEN: {verdict}")
    for f in findings:
        print(f"  [{f.severity}] {f.rule}: {f.excerpt!r}")
    return 1 if verdict == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
