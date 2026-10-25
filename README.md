# IntentLock

A hands-off issue-to-production loop where the agent must declare what it is allowed to change **before** it writes code, and deterministic scripts hold the resulting diff to that contract.

> Status: work in progress for the GitLab Transcend Hackathon ("Life After Code").

## How it works

1. An issue is picked up. The **Intent flow** (two agents, read-only then write-only) reads the untrusted issue and posts an *intent contract* as a comment.
2. The built-in **Developer flow** writes the code and opens a merge request.
3. In the merge request pipeline, `ci/run_gates.py` runs three deterministic gates: injection screen, contract validation, drift check. Any failure blocks the merge and explains why on the issue.
4. After merge: tests, scanners, build, deploy, GitLab Release, and an **evidence receipt** posted on the original issue.

The agents propose; plain Python decides. Nothing in the pass/fail path is a language model.

## Setup (one time)

1. Create a **project access token** (Settings > Access tokens), role Developer, scope `api`.
2. Add CI variable `INTENTLOCK_TOKEN` (Settings > CI/CD > Variables): **masked on, protected OFF**.
3. After the Intent flow posts its first contract, copy the commenter's username into CI variable `INTENTLOCK_CONTRACT_AUTHORS`. Only contracts from that author are accepted.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest
python -m eval.run_eval
```

## Layout

```
app/        FastAPI demo service (pricing rules)
tests/      unit tests (gates are tested against a fake GitLab)
ci/         deterministic gates: contract, injection_screen, drift_check,
            run_gates, receipt, gitlab_api, paths
flows/      Intent flow definition (GitLab Duo Agent Platform)
eval/       15-case evaluation of the gates (see eval/RESULTS.md)
```

## What the gates enforce

- **Injection screen:** blocks issue text (and human comments) that tries to override instructions, reference CI secrets, disable checks, fake authority, or hide text with invisible characters.
- **Contract validation:** the contract is written by an LLM from untrusted text, so it is validated strictly. Catch-all globs, directories, protected paths and more than 10 files are rejected.
- **Drift check:** a change fails if it touches files outside the contract, protected paths (`.gitlab-ci.yml`, `ci/`, `.gitlab/`), adds more dependencies than allowed, or removes tests. High-risk contracts never auto-merge.

## Known limitations

- A malicious change *inside* the allowed files is not detected (see case i05 in `eval/RESULTS.md`). Tests and human review of high-risk changes are the defence there.
- The injection screen is rule based and has false positives (case c05) and misses paraphrased attacks (case i04 is only caught by the drift check).
- The evaluation covers the deterministic gates only, on cases written by the author.

## License

MIT
