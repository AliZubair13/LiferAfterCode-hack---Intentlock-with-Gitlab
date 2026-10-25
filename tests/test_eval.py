"""Regression guard for the evaluation: known outcomes must not silently change."""
import json
import os

from eval.run_eval import HERE, evaluate, is_correct

EXPECTED_WRONG = {"c05", "i05"}  # one known false positive, one known miss


def test_eval_outcomes_are_stable():
    with open(os.path.join(HERE, "cases.json"), encoding="utf-8") as fh:
        cases = json.load(fh)
    assert len(cases) == 15
    wrong = {c["id"] for c in cases if not is_correct(c, evaluate(c))}
    assert wrong == EXPECTED_WRONG
