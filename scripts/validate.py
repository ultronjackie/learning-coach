"""Run decision regressions and print what they do and do not establish.

Usage from the repository root: python3 scripts/validate.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coach.decisions import (  # noqa: E402
    citation_decision,
    classify_evidence,
    next_tutor_action,
    policy_gate,
    replan,
    resolve_policy,
    accept_state,
)


def load_json(name):
    path = ROOT / "fixtures" / "synthetic" / name
    return json.loads(path.read_text(encoding="utf-8"))


def scenario_report():
    hinted = load_json("hinted_success.json")
    delayed = load_json("unseen_transfer_delayed.json")
    policy = load_json("unknown_policy.json")
    sources = load_json("sources.json")
    plan = load_json("math1860j_engr1510j_replan.json")
    legacy = (ROOT / "fixtures" / "synthetic" / "legacy_state.md").read_text(encoding="utf-8")
    formal = {
        "mode": "formal_course",
        "graded": True,
        "policy": policy["unknown_policy"],
        "learner_request": "hint",
        "attempt_submitted": True,
        "hints_already": 1,
    }
    return {
        "fixture_label": "SYNTHETIC",
        "note": "Outputs of coach.decisions on fixture inputs. Not a tutoring evaluation, course policy, or learning outcome.",
        "hinted_success": classify_evidence(hinted["hinted_unseen_success"]),
        "self_report": classify_evidence(hinted["self_report_of_mastery"]),
        "day_one_independent": classify_evidence(delayed["day_one"]),
        "next_day_retention": classify_evidence(delayed["next_local_day"]),
        "next_day_hinted": classify_evidence(delayed["next_day_hinted"]),
        "unknown_policy": resolve_policy(policy["unknown_policy"]),
        "unknown_policy_graded_answer": policy_gate(policy["unknown_policy"], "graded_answer"),
        "verified_without_statement": resolve_policy(policy["verified_flag_without_statement"]),
        "sources": {item["id"]: citation_decision(item) for item in sources["sources"]},
        "formal_hint_step": next_tutor_action(formal),
        "replan": replan(plan),
        "legacy_mode": accept_state(legacy)["mode"],
        "legacy_open_tasks": accept_state(legacy)["open_tasks"],
        "legacy_policy": accept_state(legacy)["policy"],
        "legacy_ladders": [item["ladder"] for item in accept_state(legacy)["abilities"]],
    }


def main():
    print("learning-coach decision checks")
    print("SYNTHETIC fixtures only. Not evidence of a real course policy or a learner outcome.")
    print("Decision checks execute coach/decisions.py.")
    print("Structural checks only confirm that the written procedure mentions the rule.")
    print()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print()
    print("SCENARIO OUTPUT")
    print(json.dumps(scenario_report(), ensure_ascii=False, indent=2, sort_keys=True))
    print()
    print("NOT EVALUATED")
    print("- whether a live coach follows the procedure in conversation")
    print("- tutoring quality or a learner's mastery")
    print("- real MATH1860J or ENGR1510J policies, deadlines, pages, or outcomes")
    print("- that a fixture status of verified means anyone opened a real book")
    print("- Notion, Canvas, JOJ, or Git connectivity")
    print("- prerequisite/misconception graphs or fuller adaptive retrieval")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
