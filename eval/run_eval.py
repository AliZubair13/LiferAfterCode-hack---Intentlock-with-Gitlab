"""Run the 15 evaluation cases through the deterministic gates.

    python -m eval.run_eval            # prints the table and writes eval/RESULTS.md

What this measures: the deterministic layer only (injection screen, contract
validation, drift check). The contracts in cases.json are written by hand to
stand in for what the Intent Agent would produce, and the diffs are simulated.
It does NOT measure the LLM agents.
"""
import json
import os
import sys

from ci.contract import ContractError, validate_contract
from ci.drift_check import check_drift
from ci.injection_screen import screen

HERE = os.path.dirname(os.path.abspath(__file__))


def evaluate(case):
    verdict, findings = screen(case["issue_text"])
    rules = ", ".join(f.rule for f in findings if f.severity == "high") or "-"
    if verdict == "BLOCK":
        return {"screen": verdict, "drift": "not run", "outcome": "blocked by screen",
                "detail": rules}
    try:
        contract = validate_contract(case["contract"])
    except ContractError as exc:
        return {"screen": verdict, "drift": "contract invalid",
                "outcome": "blocked by contract", "detail": str(exc)}
    d = case["diff"]
    violations = check_drift(
        contract, [tuple(c) for c in d["changes"]], d["deps"],
        d["tests_before"], d["tests_after"])
    if violations:
        return {"screen": verdict, "drift": "violation", "outcome": "blocked by drift check",
                "detail": ", ".join(v.rule for v in violations)}
    return {"screen": verdict, "drift": "clean", "outcome": "merged", "detail": "-"}


def is_correct(case, result):
    blocked = result["outcome"].startswith("blocked")
    return (not blocked) if case["category"] == "clean" else blocked


def main() -> int:
    with open(os.path.join(HERE, "cases.json"), encoding="utf-8") as fh:
        cases = json.load(fh)

    rows, tally = [], {}
    for case in cases:
        res = evaluate(case)
        ok = is_correct(case, res)
        t = tally.setdefault(case["category"], [0, 0])
        t[0] += int(ok)
        t[1] += 1
        rows.append((case, res, ok))

    lines = ["# IntentLock evaluation (15 synthetic cases)", "",
             "Scope: deterministic gates only. Cases, contracts and diffs were written by the "
             "same person who wrote the rules, so treat this as a sanity check, not a benchmark.",
             "", "| ID | Category | Screen | Drift | Outcome | Detail | Correct |",
             "|---|---|---|---|---|---|---|"]
    for case, res, ok in rows:
        lines.append(f"| {case['id']} | {case['category']} | {res['screen']} | {res['drift']} | "
                     f"{res['outcome']} | {res['detail']} | {'yes' if ok else '**NO**'} |")

    clean, over, inj = tally["clean"], tally["overreach"], tally["injected"]
    lines += ["", "## Summary", "",
              f"- Clean changes allowed through: {clean[0]}/{clean[1]} "
              f"(false positives: {clean[1] - clean[0]})",
              f"- Scope-overreach changes blocked: {over[0]}/{over[1]}",
              f"- Injected changes blocked: {inj[0]}/{inj[1]}", "", "## Notes", ""]
    for case, res, ok in rows:
        if not ok:
            lines.append(f"- **{case['id']}** ({case['category']}): {case['description']} "
                         f"Outcome was `{res['outcome']}`.")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
