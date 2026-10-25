"""Minimal GitLab REST client plus the issue/contract lookup rules.

Everything the gates need from GitLab goes through this file, so tests can
swap in a fake with the same methods.
"""
import json
import re
import urllib.parse
import urllib.request

from ci.contract import ContractError

CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)
BRANCH_RE = re.compile(r"(?:^|/)(\d+)-")
MERGE_BRANCH_RE = re.compile(r"Merge branch '([^']+)'")

GATE_MARKER = "intentlock:gate"


class GitLabAPI:
    """Talks to /projects/:id/... with a project access token (scope: api)."""

    def __init__(self, api_url: str, project_id: str, token: str):
        self.api_url = api_url.rstrip("/")
        self.project_id = project_id
        self.token = token

    def _request(self, method, path, params=None, body=None, project_scoped=True):
        base = f"{self.api_url}/projects/{self.project_id}" if project_scoped else self.api_url
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def get_issue(self, iid):
        return self._request("GET", f"/issues/{iid}")

    def list_issue_notes(self, iid):
        notes, page = [], 1
        while page <= 5:  # 500 notes is plenty for one issue
            batch = self._request("GET", f"/issues/{iid}/notes", params={
                "sort": "asc", "order_by": "created_at", "per_page": 100, "page": page})
            notes.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return notes

    def post_issue_note(self, iid, body):
        return self._request("POST", f"/issues/{iid}/notes", body={"body": body})

    def list_pipeline_jobs(self, pipeline_id):
        return self._request("GET", f"/pipelines/{pipeline_id}/jobs", params={"per_page": 100})

    def current_username(self):
        return self._request("GET", "/user", project_scoped=False)["username"]


# ---------- which issue does this change belong to? ----------

def resolve_issue_iid(branch: str = "", text: str = ""):
    """Return (iid, error). Branch name and 'Closes #N' must agree if both exist."""
    from_branch = BRANCH_RE.search(branch or "")
    from_text = CLOSES_RE.search(text or "")
    b = int(from_branch.group(1)) if from_branch else None
    t = int(from_text.group(1)) if from_text else None
    if b is not None and t is not None and b != t:
        return None, f"branch points at issue #{b} but description closes #{t}"
    iid = b if b is not None else t
    if iid is None:
        return None, "no issue reference found in branch name or description"
    return iid, None


def issue_iid_from_commit(message: str):
    """For the post-merge pipeline: read the issue from the merge commit message."""
    branch = ""
    m = MERGE_BRANCH_RE.search(message or "")
    if m:
        branch = m.group(1)
    iid, _ = resolve_issue_iid(branch, message)
    return iid


# ---------- finding the contract note ----------

def is_contract_note(note) -> bool:
    return (not note.get("system")) and "intent_contract" in (note.get("body") or "")


def author_of(note) -> str:
    return ((note.get("author") or {}).get("username")) or ""


def find_contract_note(notes, allowed_authors=()):
    """First contract-looking note (oldest first) from an allowed author.

    The first one decides. If it is invalid the caller rejects the change;
    we deliberately do NOT fall through to a later note, or an attacker
    could simply post a second, more permissive contract.
    """
    for note in notes:
        if not is_contract_note(note):
            continue
        if allowed_authors and author_of(note) not in allowed_authors:
            continue
        return note
    raise ContractError("no intent contract found on the issue")
