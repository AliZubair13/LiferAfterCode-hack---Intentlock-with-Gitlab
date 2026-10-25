"""Drift Auditor: hold a merge request to its intent contract.

Deterministic on purpose. The LLM agents write the contract and explain
findings; THIS script decides pass or fail using path matching and counting.
There is no model in the decision, so there is nothing to talk into approving.

Usage:
    python -m ci.drift_check --contract contract.md --base origin/main
Exit code 0 = within contract, 1 = violation, 2 = bad contract / usage error.
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict

from ci.contract import ContractError, parse_contract

# Never editable by an agent-authored change, whatever the contract says.
ALWAYS_FORBIDDEN = [".gitlab-ci.yml", ".gitlab/", "ci/"]

REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")
TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


@dataclass
class Violation:
    rule: str
    detail: str


def path_matches(path: str, pattern: str) -> bool:
    """True if `path` falls under `pattern` (exact, glob, or dir prefix)."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or fnmatch.fnmatch(path, pattern)


def _matches_any(path: str, patterns) -> bool:
    return any(path_matches(path, p) for p in patterns)


def check_drift(contract, changes, deps_added, tests_before, tests_after):
    """Pure decision function.

    changes:      list of (status, path), status like "A", "M", "D"
    deps_added:   list of newly added requirement names
    tests_before: test count on the base ref
    tests_after:  test count on the MR head
    Returns a list of Violation (empty means the change is within contract).
    """
    violations = []

    for status, path in changes:
        if _matches_any(path, ALWAYS_FORBIDDEN):
            violations.append(Violation(
                "protected_path", f"{path} ({status}) is protected from agent changes"))
            continue
        if _matches_any(path, contract["forbidden_paths"]):
            violations.append(Violation(
                "forbidden_path", f"{path} ({status}) is forbidden by the contract"))
            continue
        if not _matches_any(path, contract["allowed_paths"]):
            violations.append(Violation(
                "out_of_scope", f"{path} ({status}) is not in allowed_paths"))

    if len(deps_added) > contract["max_new_dependencies"]:
        violations.append(Violation(
            "new_dependencies",
            f"{len(deps_added)} new dependencies {sorted(deps_added)} "
            f"exceeds max_new_dependencies={contract['max_new_dependencies']}"))

    if tests_after < tests_before:
        violations.append(Violation(
            "tests_removed", f"test count dropped from {tests_before} to {tests_after}"))

    return violations


# ---------- git plumbing ----------

def _git(*args, cwd=None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def changed_files(base: str, cwd=None):
    out = _git("diff", "--name-status", f"{base}...HEAD", cwd=cwd)
    changes = []
    for line in out.splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        if status == "R":  # rename: count both old and new path
            changes.append(("D", parts[1]))
            changes.append(("A", parts[2]))
        else:
            changes.append((status, parts[1]))
    return changes


def _show(ref: str, path: str, cwd=None):
    try:
        return _git("show", f"{ref}:{path}", cwd=cwd)
    except subprocess.CalledProcessError:
        return None


def requirement_names(text) -> set:
    names = set()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0]
        m = REQ_NAME_RE.match(line)
        if m:
            names.add(m.group(1).lower())
    return names


def new_dependencies(base: str, cwd=None) -> list:
    before = requirement_names(_show(base, "requirements.txt", cwd))
    after = requirement_names(_show("HEAD", "requirements.txt", cwd))
    return sorted(after - before)


def count_tests(ref: str, cwd=None) -> int:
    files = _git("ls-tree", "-r", "--name-only", ref, "--", "tests", cwd=cwd).split()
    total = 0
    for path in files:
        if path.endswith(".py"):
            total += len(TEST_DEF_RE.findall(_show(ref, path, cwd) or ""))
    return total


# ---------- CLI ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", required=True, help="file containing the contract text")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--report", default="drift_report.json")
    args = ap.parse_args(argv)

    try:
        with open(args.contract, encoding="utf-8") as fh:
            contract = parse_contract(fh.read())
    except (OSError, ContractError) as exc:
        print(f"DRIFT-CHECK ERROR: cannot use contract: {exc}")
        return 2

    changes = changed_files(args.base)
    deps = new_dependencies(args.base)
    before, after = count_tests(args.base), count_tests("HEAD")
    violations = check_drift(contract, changes, deps, before, after)

    report = {
        "issue": contract["issue"],
        "risk_class": contract["risk_class"],
        "files_changed": [p for _, p in changes],
        "new_dependencies": deps,
        "tests_before": before,
        "tests_after": after,
        "passed": not violations,
        "violations": [asdict(v) for v in violations],
    }
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    if violations:
        print("DRIFT-CHECK FAILED")
        for v in violations:
            print(f"  [{v.rule}] {v.detail}")
        return 1
    print(f"DRIFT-CHECK PASSED: {len(changes)} file(s) within contract, "
          f"deps +{len(deps)}, tests {before} -> {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
