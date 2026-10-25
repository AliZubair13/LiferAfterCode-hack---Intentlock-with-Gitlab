"""Evidence receipt: one comment on the original issue summarising everything.

Runs in the post-merge pipeline. It reads the contract and the gate result
that were posted on the issue, adds the scanner and deploy results from this
pipeline, and posts a single receipt.

If INTENTLOCK_TOKEN is missing, or the commit does not refer to an issue,
it skips quietly (exit 0) so ordinary pushes keep the pipeline green.
"""
import json
import os
import sys

from ci.contract import ContractError, parse_contract
from ci.gitlab_api import (
    GATE_MARKER, GitLabAPI, author_of, find_contract_note, issue_iid_from_commit)

SCAN_JOBS = {
    "Unit tests": "unit-tests",
    "SAST": "sast",
    "Secret detection": "secret_detection",
    "Dependency scanning": "dependency_scanning",
    "Container scanning": "container_scanning",
}


def latest_gate_report(notes, trusted_user):
    """Most recent gate result posted by our own token owner (others could forge it)."""
    prefix = f"<!-- {GATE_MARKER}:"
    for note in reversed(notes):
        body = note.get("body") or ""
        if author_of(note) != trusted_user or not body.startswith(prefix):
            continue
        try:
            return json.loads(body[len(prefix):body.index(" -->")])
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def scan_results(jobs):
    """Map friendly name -> status using substring match on job names."""
    out = {}
    for label, needle in SCAN_JOBS.items():
        statuses = [j["status"] for j in jobs if needle in j["name"]]
        out[label] = statuses[-1] if statuses else "not run"
    return out


def render_receipt(data) -> str:
    c = data.get("contract") or {}
    gate = data.get("gate") or {}
    drift = gate.get("drift") or {}
    inj = (gate.get("injection") or {}).get("verdict", "n/a")
    scans = data.get("scans", {})
    lines = [f"## Evidence Receipt - issue #{data['issue']}", ""]
    lines.append(f"- **Intent contract:** risk `{c.get('risk_class', 'n/a')}`, "
                 f"{len(c.get('allowed_paths', []))} file(s) allowed")
    lines.append(f"- **Injection screen:** {inj}")
    if drift:
        lines.append(f"- **Drift audit:** {'PASS' if gate.get('passed') else 'FAIL'} - "
                     f"{len(drift.get('files_changed', []))} file(s) changed, "
                     f"dependencies +{len(drift.get('new_dependencies', []))}, "
                     f"tests {drift.get('tests_before')} -> {drift.get('tests_after')}")
    else:
        lines.append("- **Drift audit:** no gate result found on the issue")
    for label, status in scans.items():
        lines.append(f"- **{label}:** {status}")
    lines.append(f"- **Deploy:** {data.get('deploy', 'n/a')}")
    lines.append(f"- **Commit:** `{data.get('commit', 'n/a')}`  |  "
                 f"**Pipeline:** {data.get('pipeline_url', 'n/a')}")
    if c.get("acceptance_criteria"):
        lines += ["", "Acceptance criteria from the contract:"]
        lines += [f"- {a}" for a in c["acceptance_criteria"]]
    if data.get("rollback"):
        lines += ["", f"Rollback: `{data['rollback']}`"]
    return "\n".join(lines)


def build_receipt(api, iid, pipeline_id, env, allowed_authors=()):
    notes = api.list_issue_notes(iid)
    data = {
        "issue": iid,
        "commit": env.get("CI_COMMIT_SHORT_SHA", "n/a"),
        "pipeline_url": env.get("CI_PIPELINE_URL", "n/a"),
        "deploy": env.get("DEPLOY_SUMMARY", "stub (no cloud deploy configured yet)"),
        "rollback": env.get("ROLLBACK_COMMAND", ""),
        "gate": latest_gate_report(notes, api.current_username()),
        "scans": scan_results(api.list_pipeline_jobs(pipeline_id)),
    }
    try:
        data["contract"] = parse_contract(find_contract_note(notes, allowed_authors)["body"])
    except ContractError:
        data["contract"] = {}
    return render_receipt(data)


def main() -> int:
    token = os.environ.get("INTENTLOCK_TOKEN")
    if not token:
        print("RECEIPT SKIPPED: INTENTLOCK_TOKEN is not set.")
        return 0
    iid = issue_iid_from_commit(os.environ.get("CI_COMMIT_MESSAGE", ""))
    if iid is None:
        print("RECEIPT SKIPPED: commit message does not reference an issue.")
        return 0
    authors = tuple(a.strip() for a in os.environ.get(
        "INTENTLOCK_CONTRACT_AUTHORS", "").split(",") if a.strip())
    api = GitLabAPI(os.environ["CI_API_V4_URL"], os.environ["CI_PROJECT_ID"], token)
    body = build_receipt(api, iid, os.environ["CI_PIPELINE_ID"], os.environ, authors)
    api.post_issue_note(iid, body)
    print(f"RECEIPT POSTED on issue #{iid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
