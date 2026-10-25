"""Run every gate for a merge request and post the result on the issue.

Order: injection screen -> contract (validated) -> drift check.
The first failing gate stops the run. Everything here is deterministic.

Usage (inside a merge request pipeline):
    python -m ci.run_gates --base "$CI_MERGE_REQUEST_DIFF_BASE_SHA"
Environment: CI_API_V4_URL, CI_PROJECT_ID, INTENTLOCK_TOKEN,
             CI_MERGE_REQUEST_SOURCE_BRANCH_NAME, CI_MERGE_REQUEST_DESCRIPTION,
             INTENTLOCK_CONTRACT_AUTHORS (optional, comma separated usernames)
Exit code 0 = all gates passed, 1 = blocked.
"""
import argparse
import json
import os
import sys
from dataclasses import asdict

from ci.contract import ContractError, parse_contract
from ci.drift_check import (
    changed_files, check_drift, count_tests, new_dependencies)
from ci.gitlab_api import (
    GATE_MARKER, GitLabAPI, author_of, find_contract_note, is_contract_note,
    resolve_issue_iid)
from ci.injection_screen import screen


def git_diff_provider(base):
    def provider():
        return (changed_files(base), new_dependencies(base),
                count_tests(base), count_tests("HEAD"))
    return provider


def _texts_to_screen(issue, notes, contract_note, bot_users):
    texts = [issue.get("title") or "", issue.get("description") or ""]
    for note in notes:
        if note.get("system") or note is contract_note:
            continue
        if bot_users and author_of(note) in bot_users:
            continue
        texts.append(note.get("body") or "")
    return "\n".join(texts)


def run_gates(api, iid, diff_provider, allowed_authors=()):
    """Return (exit_code, report). `api` needs get_issue, list_issue_notes, post_issue_note."""
    report = {"issue": iid, "passed": False, "failed_gate": None, "reasons": []}

    issue = api.get_issue(iid)
    notes = api.list_issue_notes(iid)

    # Gate 0: there must be a contract, written before the code.
    contract_note = None
    try:
        contract_note = find_contract_note(notes, allowed_authors)
    except ContractError as exc:
        report.update(failed_gate="contract", reasons=[str(exc)])
        return _finish(api, iid, report, 1)

    # Gate 1: injection screen over the issue and its human comments.
    verdict, findings = screen(_texts_to_screen(issue, notes, contract_note, allowed_authors))
    report["injection"] = {"verdict": verdict, "findings": [asdict(f) for f in findings]}
    if verdict == "BLOCK":
        report.update(failed_gate="injection", reasons=[
            f"{f.rule} ({f.severity})" for f in findings if f.severity == "high"])
        return _finish(api, iid, report, 1)

    # Gate 2: the contract itself must be sane (no catch-alls, no protected paths).
    try:
        contract = parse_contract(contract_note["body"])
    except ContractError as exc:
        report.update(failed_gate="contract", reasons=[str(exc)])
        return _finish(api, iid, report, 1)
    report["contract"] = contract

    # Gate 3: the diff must stay inside the contract.
    changes, deps, before, after = diff_provider()
    violations = check_drift(contract, changes, deps, before, after)
    report["drift"] = {
        "files_changed": [p for _, p in changes],
        "new_dependencies": deps,
        "tests_before": before,
        "tests_after": after,
        "violations": [asdict(v) for v in violations],
    }
    if violations:
        report.update(failed_gate="drift", reasons=[f"{v.rule}: {v.detail}" for v in violations])
        return _finish(api, iid, report, 1)

    report["passed"] = True
    return _finish(api, iid, report, 0)


def render_gate_note(report) -> str:
    payload = json.dumps(report, separators=(",", ":"))
    status = "PASSED" if report["passed"] else f"BLOCKED at the {report['failed_gate']} gate"
    lines = [f"<!-- {GATE_MARKER}:{payload} -->",
             f"**IntentLock gates: {status}** (issue #{report['issue']})", ""]
    if report["passed"]:
        d = report["drift"]
        lines += [f"- Injection screen: {report['injection']['verdict']}",
                  f"- Drift audit: {len(d['files_changed'])} file(s) within contract, "
                  f"dependencies +{len(d['new_dependencies'])}, "
                  f"tests {d['tests_before']} -> {d['tests_after']}"]
    else:
        lines += [f"- {r}" for r in report["reasons"]]
    return "\n".join(lines)


def _finish(api, iid, report, code):
    try:
        api.post_issue_note(iid, render_gate_note(report))
    except Exception as exc:  # posting is a courtesy; the exit code is the gate
        print(f"WARNING: could not post gate note to issue: {exc}")
    return code, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="commit the merge request branched from")
    ap.add_argument("--issue", type=int, help="override issue IID detection")
    ap.add_argument("--report", default="gates_report.json")
    args = ap.parse_args(argv)

    token = os.environ.get("INTENTLOCK_TOKEN")
    if not token:
        print("GATES ERROR: INTENTLOCK_TOKEN is not set. Failing closed.")
        return 1

    iid = args.issue
    if iid is None:
        iid, err = resolve_issue_iid(
            os.environ.get("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME", ""),
            os.environ.get("CI_MERGE_REQUEST_DESCRIPTION", "")
            + "\n" + os.environ.get("CI_MERGE_REQUEST_TITLE", ""))
        if iid is None:
            print(f"GATES ERROR: {err}. Failing closed.")
            return 1

    authors = tuple(a.strip() for a in os.environ.get(
        "INTENTLOCK_CONTRACT_AUTHORS", "").split(",") if a.strip())
    if not authors:
        print("WARNING: INTENTLOCK_CONTRACT_AUTHORS not set; "
              "accepting the oldest contract from any author.")

    api = GitLabAPI(os.environ["CI_API_V4_URL"], os.environ["CI_PROJECT_ID"], token)
    code, report = run_gates(api, iid, git_diff_provider(args.base), authors)

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    if code == 0:
        print(f"GATES PASSED for issue #{iid}")
    else:
        print(f"GATES BLOCKED for issue #{iid} at the {report['failed_gate']} gate:")
        for reason in report["reasons"]:
            print(f"  - {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
