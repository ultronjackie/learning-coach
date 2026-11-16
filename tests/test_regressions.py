"""Regression checks for coach.decisions.

These tests execute the decision functions on SYNTHETIC fixtures. They do not
evaluate a live tutoring session, a real course policy, or a learner outcome.
Documentation pins only check that the written procedure states the rule.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from coach.decisions import (
    LADDER,
    accept_state,
    citation_decision,
    classify_evidence,
    next_tutor_action,
    normalize_signals,
    policy_gate,
    qualifies_as_prior_independent,
    replan,
    resolve_policy,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic"


def load_json(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    if "SYNTHETIC" not in text:
        raise AssertionError(name + " is not labeled SYNTHETIC")
    return json.loads(text)


def load_text(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    if "SYNTHETIC" not in text:
        raise AssertionError(name + " is not labeled SYNTHETIC")
    return text


class HintedSuccess(unittest.TestCase):
    def test_hinted_unseen_success_is_not_independent_mastery(self):
        fixture = load_json("hinted_success.json")
        result = classify_evidence(fixture["hinted_unseen_success"])
        self.assertEqual(result["ladder"], "辅助完成")
        self.assertFalse(result["independent_mastery"])
        self.assertFalse(result["delayed_retention"])
        self.assertIn("assisted_success_is_not_independent_mastery", result["reasons"])
        self.assertEqual(result["assistance"], "hint")

    def test_self_report_does_not_become_observed_mastery(self):
        fixture = load_json("hinted_success.json")
        result = classify_evidence(fixture["self_report_of_mastery"])
        self.assertEqual(result["ladder"], "已接触")
        self.assertEqual(result["source_kind"], "self_report")
        self.assertFalse(result["independent_mastery"])
        self.assertFalse(result["delayed_retention"])

    def test_same_item_success_needs_unseen_transfer(self):
        fixture = load_json("hinted_success.json")
        result = classify_evidence(fixture["same_item_unassisted"])
        self.assertEqual(result["ladder"], "已接触")
        self.assertFalse(result["independent_mastery"])
        self.assertTrue(result["observed_unassisted_success"])
        self.assertIn("unseen_transfer_required_for_independent_mastery", result["reasons"])


class UnseenTransferAndDelay(unittest.TestCase):
    def test_independent_unseen_transfer_then_next_day_retention(self):
        fixture = load_json("unseen_transfer_delayed.json")
        day_one = classify_evidence(fixture["day_one"])
        same_day = classify_evidence(fixture["same_local_day"])
        next_day = classify_evidence(fixture["next_local_day"])
        same_task = classify_evidence(fixture["same_task_next_day"])
        hinted = classify_evidence(fixture["next_day_hinted"])
        after_hint = classify_evidence(fixture["next_day_after_hinted_prior"])

        self.assertEqual(day_one["ladder"], "独立完成")
        self.assertTrue(day_one["independent_mastery"])
        self.assertFalse(day_one["delayed_retention"])

        self.assertEqual(same_day["ladder"], "独立完成")
        self.assertFalse(same_day["delayed_retention"])
        self.assertIn("delayed_retention_requires_a_later_local_date", same_day["reasons"])

        self.assertEqual(next_day["ladder"], "延迟保持")
        self.assertTrue(next_day["independent_mastery"])
        self.assertTrue(next_day["delayed_retention"])

        self.assertEqual(same_task["ladder"], "独立完成")
        self.assertFalse(same_task["delayed_retention"])
        self.assertIn("delayed_check_requires_a_different_task", same_task["reasons"])

        self.assertEqual(hinted["ladder"], "辅助完成")
        self.assertFalse(hinted["independent_mastery"])
        self.assertFalse(hinted["delayed_retention"])

        self.assertEqual(after_hint["ladder"], "独立完成")
        self.assertFalse(after_hint["delayed_retention"])
        self.assertIn("prior_was_not_independent_unseen_transfer", after_hint["reasons"])

    def test_local_midnight_counts_as_the_next_local_day(self):
        prior = {
            "source_kind": "observed",
            "timestamp": "2026-11-15T23:30:00+08:00",
            "assistance": "none",
            "performance": "successful",
            "seen_before": False,
            "transfer": True,
            "task_id": "synthetic-late",
        }
        current = dict(prior)
        current["timestamp"] = "2026-11-16T00:30:00+08:00"
        current["task_id"] = "synthetic-after-midnight"
        current["prior_independent"] = prior
        result = classify_evidence(current)
        self.assertEqual(result["ladder"], "延迟保持")

    def test_naive_timestamp_cannot_support_an_independent_claim(self):
        result = classify_evidence({
            "source_kind": "observed",
            "timestamp": "2026-11-16T09:00:00",
            "assistance": "none",
            "performance": "successful",
            "seen_before": False,
            "transfer": True,
            "task_id": "synthetic-naive",
        })
        self.assertEqual(result["ladder"], "已接触")
        self.assertFalse(result["independent_mastery"])
        self.assertIn("timestamp_required_for_independent_claim", result["reasons"])


class PolicyAndSources(unittest.TestCase):
    def test_unknown_policy_stays_conservative_and_invents_nothing(self):
        fixture = load_json("unknown_policy.json")
        self.assertIn("MATH1860J", fixture["disclaimer"])
        resolved = resolve_policy(fixture["unknown_policy"])
        self.assertEqual(resolved["status"], "unknown")
        self.assertIsNone(resolved["statement"])
        self.assertFalse(resolved["invented_policy"])

        concepts = policy_gate(fixture["unknown_policy"], "general_concept")
        clarification = policy_gate(fixture["unknown_policy"], "policy_clarification")
        graded = policy_gate(fixture["unknown_policy"], "graded_answer")
        draft = policy_gate(fixture["unknown_policy"], "submission_draft")
        self.assertTrue(concepts["allow"])
        self.assertTrue(clarification["allow"])
        self.assertFalse(graded["allow"])
        self.assertFalse(draft["allow"])
        self.assertFalse(graded["coach_emits_graded_solution"])
        self.assertIsNone(graded["course_policy_allows_graded_answers"])
        self.assertIsNone(graded["course_policy_forbids_graded_answers"])
        self.assertIsNone(graded["policy_statement_used"])

    def test_conflicting_and_unverifiable_flags_do_not_invent_a_policy(self):
        fixture = load_json("unknown_policy.json")
        conflict = resolve_policy(fixture["conflicting_policy"])
        self.assertEqual(conflict["status"], "conflicting")
        self.assertIsNone(conflict["statement"])
        missing = resolve_policy(fixture["verified_flag_without_statement"])
        self.assertEqual(missing["status"], "unknown")
        self.assertIsNone(missing["statement"])
        self.assertEqual(missing["reason"], "verified_flag_without_recorded_statement")

    def test_verified_allowance_is_quoted_not_rewritten(self):
        fixture = load_json("unknown_policy.json")
        resolved = resolve_policy(fixture["verified_synthetic_statement"])
        self.assertEqual(resolved["status"], "verified")
        self.assertTrue(resolved["statement"].startswith("SYNTHETIC POLICY TEXT"))
        graded = policy_gate(fixture["verified_synthetic_statement"], "graded_answer")
        self.assertFalse(graded["allow"])
        self.assertTrue(graded["course_policy_allows_graded_answers"])
        self.assertFalse(graded["course_policy_forbids_graded_answers"])
        self.assertFalse(graded["coach_emits_graded_solution"])
        self.assertEqual(graded["policy_statement_used"], resolved["statement"])

    def test_verified_and_unverified_locations(self):
        fixture = load_json("sources.json")
        by_id = {item["id"]: citation_decision(item) for item in fixture["sources"]}

        section = by_id["section-checked-no-page"]
        self.assertTrue(section["may_cite_location"])
        self.assertEqual(section["location_used"], "SYNTHETIC-TEXT section 1 definition A")
        self.assertFalse(section["may_cite_page"])
        self.assertIsNone(section["page_used"])
        self.assertFalse(section["invented_page"])

        page = by_id["page-checked"]
        self.assertEqual(page["page_used"], "SYNTHETIC-p-12")
        self.assertEqual(page["location_used"], "SYNTHETIC-TEXT section 1")

        withheld = by_id["unverified-has-page-string"]
        self.assertFalse(withheld["may_cite_location"])
        self.assertFalse(withheld["may_cite_page"])
        self.assertIsNone(withheld["location_used"])
        self.assertIsNone(withheld["page_used"])

        unknown = by_id["unknown-source"]
        self.assertFalse(unknown["may_cite_location"])
        self.assertIsNone(unknown["page_used"])

        for source in fixture["sources"]:
            decision = citation_decision(source)
            if decision["page_used"] is not None:
                self.assertEqual(decision["page_used"], source["page"].strip())
            if decision["location_used"] is not None:
                self.assertEqual(decision["location_used"], source["location"].strip())


class TutoringProcedure(unittest.TestCase):
    def test_formal_unknown_graded_layers_stop_before_a_solution(self):
        policy = load_json("unknown_policy.json")["unknown_policy"]
        base = {
            "mode": "formal_course",
            "graded": True,
            "policy": policy,
            "attempt_submitted": True,
            "teachback_done": False,
            "transfer_assigned": False,
        }
        expected = [
            (0, "orient_concept", "hint"),
            (1, "strategic_hint", "hint"),
            (2, "partial_structure", "hint"),
            (3, "request_teachback", "none"),
            (4, "stop_and_wait", "none"),
        ]
        for layer, action, assistance in expected:
            session = dict(base)
            session["learner_request"] = "hint"
            session["hints_already"] = layer
            result = next_tutor_action(session)
            self.assertEqual(result["action"], action)
            self.assertEqual(result["assistance"], assistance)
            self.assertFalse(result["counts_as_independent_mastery"])
            self.assertFalse(result["emits_graded_solution"])
            self.assertNotIn("solution", result)

        no_attempt = dict(base)
        no_attempt["attempt_submitted"] = False
        no_attempt["learner_request"] = "hint"
        self.assertEqual(next_tutor_action(no_attempt)["action"], "restate_attempt")

        answer = dict(base)
        answer["learner_request"] = "answer"
        refused = next_tutor_action(answer)
        self.assertEqual(refused["action"], "refuse_graded_completion")
        self.assertEqual(refused["follow_up"], "request_policy")
        self.assertFalse(refused["emits_graded_solution"])
        self.assertFalse(refused["invented_policy"])

        teachback = dict(base)
        teachback["teachback_done"] = True
        transfer = next_tutor_action(teachback)
        self.assertEqual(transfer["action"], "assign_unseen_transfer")
        self.assertTrue(transfer["transfer_must_be_unseen"])
        self.assertTrue(transfer["not_the_graded_submission"])

    def test_hint_recorded_from_the_procedure_blocks_mastery(self):
        policy = load_json("unknown_policy.json")["unknown_policy"]
        step = next_tutor_action({
            "mode": "formal_course",
            "graded": True,
            "policy": policy,
            "learner_request": "hint",
            "attempt_submitted": True,
            "hints_already": 1,
        })
        self.assertEqual(step["assistance"], "hint")
        record = classify_evidence({
            "source_kind": "observed",
            "timestamp": "2026-11-16T10:00:00+08:00",
            "assistance": step["assistance"],
            "performance": "successful",
            "seen_before": False,
            "transfer": True,
            "task_id": "synthetic-after-hint",
        })
        self.assertEqual(record["ladder"], "辅助完成")
        self.assertFalse(record["independent_mastery"])

    def test_self_study_answer_is_assistance_and_graded_work_still_refuses(self):
        explained = next_tutor_action({
            "mode": "self_study",
            "graded": False,
            "learner_request": "answer",
            "attempt_submitted": False,
        })
        self.assertEqual(explained["action"], "fuller_explanation")
        self.assertEqual(explained["assistance"], "answer_shown")
        self.assertFalse(explained["counts_as_independent_mastery"])
        graded = next_tutor_action({
            "mode": "self_study",
            "graded": True,
            "learner_request": "answer",
            "attempt_submitted": True,
        })
        self.assertEqual(graded["action"], "refuse_graded_completion")
        self.assertFalse(graded["emits_graded_solution"])

    def test_verified_analogies_are_allowed_and_graded_completion_is_not(self):
        policy = load_json("unknown_policy.json")["verified_synthetic_statement"]
        step = next_tutor_action({
            "mode": "formal_course",
            "graded": True,
            "policy": policy,
            "learner_request": "hint",
            "attempt_submitted": True,
            "hints_already": 3,
        })
        self.assertEqual(step["action"], "analogous_example")
        self.assertEqual(step["assistance"], "worked_example")
        self.assertTrue(step["graded_item_excluded"])
        refused = next_tutor_action({
            "mode": "formal_course",
            "graded": True,
            "policy": policy,
            "learner_request": "submission",
            "attempt_submitted": True,
        })
        self.assertEqual(refused["action"], "refuse_graded_completion")
        self.assertTrue(refused["course_policy_allows_graded_answers"])
        distinct = policy_gate(policy, "analogous_example", distinct_from_graded_item=False)
        self.assertFalse(distinct["allow"])

    def test_no_graded_session_emits_a_solution_or_mastery(self):
        policies = [
            None,
            {"status": "unknown"},
            {"status": "conflicting"},
            {"status": "verified", "statement_present": False, "statement": "SYNTHETIC"},
            load_json("unknown_policy.json")["verified_synthetic_statement"],
            {
                "status": "verified",
                "statement_present": True,
                "statement": "SYNTHETIC POLICY TEXT. Hints and concepts are disallowed.",
                "allowances": {"hints_without_solution": False, "general_concepts": False},
            },
        ]
        requests = ("hint", "explain", "answer", "submission", "continue", "concept", "policy")
        for mode in ("self_study", "formal_course"):
            for graded in (False, True):
                for request in requests:
                    for policy in policies:
                        for layer in (0, 1, 2, 3, 4, 5):
                            result = next_tutor_action({
                                "mode": mode,
                                "graded": graded,
                                "policy": policy,
                                "learner_request": request,
                                "attempt_submitted": layer > 0,
                                "hints_already": layer,
                                "teachback_done": layer >= 5,
                                "transfer_assigned": False,
                            })
                            self.assertFalse(result["counts_as_independent_mastery"])
                            self.assertFalse(result["emits_graded_solution"])
                            self.assertFalse(result["invented_policy"])
                            if graded:
                                self.assertNotEqual(result["action"], "fuller_explanation")
                            if graded and request in ("answer", "submission"):
                                self.assertEqual(result["action"], "refuse_graded_completion")


class SignalsAndReplan(unittest.TestCase):
    def test_missing_canvas_does_not_imply_joj_or_git(self):
        only_canvas = normalize_signals({"canvas": "missing"})
        self.assertEqual(only_canvas["canvas"]["status"], "missing")
        self.assertEqual(only_canvas["joj"]["status"], "unknown")
        self.assertEqual(only_canvas["git"]["status"], "unknown")
        self.assertFalse(only_canvas["joj"]["implied_by_other_system"])
        self.assertFalse(only_canvas["git"]["implied_by_other_system"])

        conflict = normalize_signals({"canvas": {"reports": ["missing", "submitted"]}, "git": "submitted"})
        self.assertEqual(conflict["canvas"]["status"], "conflicting")
        self.assertEqual(conflict["joj"]["status"], "unknown")
        self.assertEqual(conflict["git"]["status"], "submitted")

    def test_math_and_engr_fixture_replans_without_dropping_or_mixing_signals(self):
        fixture = load_json("math1860j_engr1510j_replan.json")
        self.assertIn("MATH1860J", fixture["disclaimer"])
        self.assertIn("ENGR1510J", fixture["disclaimer"])
        result = replan(fixture)

        self.assertEqual(result["ordered_course_ids"], ["SYNTHETIC-MATH1860J", "SYNTHETIC-ENGR1510J"])
        math_signals = result["signals_by_course"]["SYNTHETIC-MATH1860J"]
        engr_signals = result["signals_by_course"]["SYNTHETIC-ENGR1510J"]
        self.assertEqual(math_signals["canvas"]["status"], "missing")
        self.assertEqual(math_signals["joj"]["status"], "unknown")
        self.assertEqual(math_signals["git"]["status"], "unknown")
        self.assertEqual(engr_signals["git"]["status"], "submitted")
        self.assertEqual(engr_signals["canvas"]["status"], "unknown")
        self.assertEqual(engr_signals["joj"]["status"], "unknown")
        self.assertEqual(result["policy_status_by_course"]["SYNTHETIC-MATH1860J"], "unknown")
        self.assertFalse(result["invented_deadline"])
        self.assertFalse(result["invented_submission"])
        self.assertEqual(result["mastery_updates"], [])

        scheduled = {(item["task_id"], item["minutes"]) for item in result["scheduled"]}
        self.assertEqual(scheduled, {
            ("m-read-3", 40),
            ("gap:epsilon-delta:m-practice-3", 20),
            ("m-practice-3", 30),
        })
        retained = {item["task_id"]: item for item in result["retained_unscheduled"]}
        self.assertEqual(retained["m-practice-3"]["minutes"], 20)
        self.assertEqual(retained["m-practice-3"]["reason"], "partial_block")
        self.assertFalse(retained["m-practice-3"]["completed"])
        self.assertEqual(retained["m-submit"]["reason"], "no_fitting_block")
        self.assertEqual(retained["m-omitted"]["reason"], "duration_unknown")
        self.assertTrue(retained["m-omitted"]["from_missed_session"])
        self.assertEqual(retained["e-lab"]["reason"], "deadline_conflict")
        self.assertEqual(retained["e-concept"]["reason"], "no_fitting_block")
        self.assertNotIn("e-lab", {item["task_id"] for item in result["scheduled"]})

        present = {item["task_id"] for item in result["scheduled"]} | set(retained)
        for task_id in fixture["missed_session"]["task_ids"]:
            self.assertIn(task_id, present)
        self.assertFalse(result["missed_session"]["dropped"])
        self.assertTrue(all(item["present"] for item in result["missed_session"]["tasks_still_present"]))
        deadline_conflicts = [item for item in result["conflicts"] if item.get("field") == "deadline"]
        self.assertEqual(deadline_conflicts[0]["reports"], ["2026-11-17", "2026-11-20"])
        self.assertNotIn("2026-11-17", result["ordered_course_ids"])

    def test_priority_unknowns_and_missed_session_without_blocks(self):
        result = replan({
            "blocks": None,
            "missed_session": {
                "course_id": "SYNTHETIC-MATH1860J",
                "when": "2026-11-15T19:00:00+08:00",
                "task_ids": ["kept-task"],
            },
            "courses": [
                {
                    "id": "SYNTHETIC-LATER",
                    "deadline_status": "known",
                    "deadline": "2026-11-20T12:00:00+08:00",
                    "tasks": [{"id": "later", "minutes": 30, "kind": "reading", "required": True}],
                },
                {
                    "id": "SYNTHETIC-SOON",
                    "deadline_status": "known",
                    "deadline": "2026-11-18T12:00:00+08:00",
                    "tasks": [{"id": "soon", "minutes": 30, "kind": "reading", "required": True}],
                },
                {
                    "id": "SYNTHETIC-UNKNOWN",
                    "deadline_status": "unknown",
                    "tasks": [{"id": "undated", "minutes": 15, "kind": "practice", "required": True}],
                },
                {
                    "id": "SYNTHETIC-CONFLICT",
                    "deadline_status": "conflicting",
                    "deadline_reports": ["2026-11-17", "2026-11-21"],
                    "tasks": [{"id": "blocked-submit", "minutes": 15, "kind": "submission", "required": True}],
                },
                {
                    "id": "SYNTHETIC-BAD-DATE",
                    "deadline_status": "known",
                    "deadline": "tomorrow",
                    "tasks": [{"id": "bad-date", "minutes": 10, "kind": "reading"}],
                },
            ],
        })
        self.assertEqual(result["ordered_course_ids"][:2], ["SYNTHETIC-SOON", "SYNTHETIC-LATER"])
        self.assertLess(
            result["ordered_course_ids"].index("SYNTHETIC-UNKNOWN"),
            result["ordered_course_ids"].index("SYNTHETIC-CONFLICT"),
        )
        self.assertEqual(result["schedule_status"], "schedule_unknown")
        self.assertEqual(result["scheduled"], [])
        retained_ids = {item["task_id"] for item in result["retained_unscheduled"]}
        self.assertIn("kept-task", retained_ids)
        self.assertIn("soon", retained_ids)
        self.assertIn("blocked-submit", retained_ids)
        self.assertTrue(all(item["present"] for item in result["missed_session"]["tasks_still_present"]))
        self.assertNotIn("tomorrow", json.dumps(result))
        self.assertTrue(any(item.get("reason") == "known_flag_without_timestamp" for item in result["unknowns"]))

    def test_overlapping_blocks_are_not_silently_merged(self):
        result = replan({
            "blocks": [
                {"id": "a", "start": "2026-11-16T19:00:00+08:00", "end": "2026-11-16T20:00:00+08:00"},
                {"id": "b", "start": "2026-11-16T19:30:00+08:00", "end": "2026-11-16T20:30:00+08:00"},
            ],
            "courses": [{
                "id": "SYNTHETIC-ONE",
                "deadline_status": "known",
                "deadline": "2026-11-18T12:00:00+08:00",
                "tasks": [{"id": "task", "minutes": 30, "kind": "reading", "required": True}],
            }],
        })
        self.assertEqual(result["schedule_status"], "block_conflict")
        self.assertEqual(result["scheduled"], [])
        self.assertEqual(result["retained_unscheduled"][0]["task_id"], "task")
        self.assertEqual(result["retained_unscheduled"][0]["reason"], "block_conflict")

    def test_missing_gap_duration_is_not_invented(self):
        result = replan({
            "blocks": [{
                "id": "hour",
                "start": "2026-11-16T19:00:00+08:00",
                "end": "2026-11-16T20:00:00+08:00",
            }],
            "courses": [{
                "id": "SYNTHETIC-GAP",
                "deadline_status": "known",
                "deadline": "2026-11-18T12:00:00+08:00",
                "tasks": [{
                    "id": "practice",
                    "minutes": 30,
                    "kind": "practice",
                    "blocked_by_gap": "definition",
                    "gap_ladder": "已接触",
                }],
            }],
        })
        self.assertEqual(result["scheduled"], [])
        reasons = {item["task_id"]: item["reason"] for item in result["retained_unscheduled"]}
        self.assertEqual(reasons["practice"], "blocked_gap_duration_unknown")
        self.assertIn("gap:definition:practice", reasons)


class LegacySelfStudy(unittest.TestCase):
    def test_v0_file_migrates_without_dropping_or_inventing(self):
        text = load_text("legacy_state.md")
        migrated = accept_state(text)
        self.assertEqual(migrated["schema"], "learning-coach.state/v1")
        self.assertEqual(migrated["mode"], "self_study")
        self.assertEqual(migrated["course_id"], "synthetic-french-daily")
        self.assertEqual(migrated["authority"], {"role": "local", "store": "filesystem"})
        self.assertIsNone(migrated["policy"])
        self.assertEqual(migrated["evidence_records"], [])
        self.assertEqual(migrated["dropped_sections"], [])
        self.assertFalse(migrated["invented_policy"])
        self.assertFalse(migrated["invented_pages"])
        self.assertFalse(migrated["integrations_required"])
        self.assertEqual(migrated["original_text_retained"], text)
        self.assertIn("无页码", migrated["reading_task"])
        self.assertIn("每课约 2 小时", migrated["time_notes"])
        self.assertIn("保留这一段", migrated["preserved_sections"]["用户额外笔记"])
        self.assertTrue(any(task.startswith("q1:") for task in migrated["open_tasks"]))
        self.assertTrue(any("询问时间" in item for item in migrated["retests"]))

        ladders = [item["ladder"] for item in migrated["abilities"]]
        for level in LADDER:
            self.assertIn(level, ladders)
        stored = {item["skill"]: item for item in migrated["abilities"]}
        self.assertEqual(stored["自报会写邮件"]["ladder"], "独立完成")
        self.assertEqual(stored["自报会写邮件"]["source_kind"], "self_report")
        self.assertEqual(stored["自报会写邮件"]["conflict"], "self_report_stored_as_独立完成")
        self.assertFalse(stored["自报会写邮件"]["use_for_new_independent_claim"])
        self.assertEqual(stored["独立点餐"]["ladder"], "独立完成")
        for item in migrated["abilities"]:
            self.assertTrue(item["legacy_projection"])
            self.assertFalse(qualifies_as_prior_independent(item))

    def test_explicit_notion_authority_is_single_and_signals_stay_separate(self):
        migrated = accept_state({
            "schema": "learning-coach.state/v1",
            "mode": "formal_course",
            "authority": {"role": "notion", "store": "notion"},
            "authorities": [
                {"role": "local", "store": "filesystem"},
                {"role": "notion", "store": "notion"},
            ],
            "open_tasks": ["keep-me"],
            "policy": {"status": "verified", "statement_present": False},
            "signals": {"canvas": "missing"},
        })
        self.assertEqual(migrated["authority"], {"role": "notion", "store": "notion"})
        self.assertNotIn("authorities", migrated)
        self.assertEqual(migrated["open_tasks"], ["keep-me"])
        self.assertEqual(migrated["policy"]["status"], "unknown")
        self.assertIsNone(migrated["policy"]["statement"])
        self.assertEqual(migrated["signals"]["canvas"]["status"], "missing")
        self.assertEqual(migrated["signals"]["joj"]["status"], "unknown")
        self.assertEqual(migrated["signals"]["git"]["status"], "unknown")
        self.assertFalse(migrated["integrations_required"])

    def test_ladder_is_unchanged(self):
        self.assertEqual(LADDER, ("未测", "已接触", "辅助完成", "独立完成", "延迟保持"))


class DocumentationPins(unittest.TestCase):
    """Presence checks for the written procedure. Not a tutoring evaluation."""

    def test_skill_points_at_the_new_procedures(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name in (
            "references/formal-course.md",
            "references/evidence.md",
            "references/tutoring.md",
            "references/replan.md",
            "references/state-interface.md",
            "references/follow-ups.md",
        ):
            self.assertIn(name, skill)
            self.assertTrue((ROOT / name).is_file())

    def test_procedures_state_the_rules(self):
        formal = (ROOT / "references" / "formal-course.md").read_text(encoding="utf-8")
        evidence = (ROOT / "references" / "evidence.md").read_text(encoding="utf-8")
        tutoring = (ROOT / "references" / "tutoring.md").read_text(encoding="utf-8")
        replan_doc = (ROOT / "references" / "replan.md").read_text(encoding="utf-8")
        interface = (ROOT / "references" / "state-interface.md").read_text(encoding="utf-8")
        follow = (ROOT / "references" / "follow-ups.md").read_text(encoding="utf-8")
        first = (ROOT / "references" / "first-use.md").read_text(encoding="utf-8")
        self.assertIn("不编造", formal)
        self.assertIn("计分", formal)
        self.assertIn("政策未知", formal)
        for level in LADDER:
            self.assertIn(level, evidence)
        self.assertIn("自报", evidence)
        self.assertIn("未见", evidence)
        self.assertIn("复述", tutoring)
        self.assertIn("未见", tutoring)
        self.assertIn("拒绝", tutoring)
        self.assertIn("Canvas", replan_doc)
        self.assertIn("JOJ", replan_doc)
        self.assertIn("Git", replan_doc)
        self.assertIn("错过", replan_doc)
        self.assertIn("learning-coach.state/v0", interface)
        self.assertIn("learning-coach.state/v1", interface)
        self.assertIn("learning-coach.evidence/v1", interface)
        self.assertIn("notion", interface)
        self.assertIn("先修", follow)
        self.assertIn("误解", follow)
        self.assertIn("自适应提取", follow)
        self.assertIn("SYNTHETIC", first)

    def test_private_state_stays_out_of_the_repo_contract(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/Self-Study/", ignore)
        self.assertIn("/references/storage.local.md", ignore)
        module = (ROOT / "coach" / "decisions.py").read_text(encoding="utf-8")
        self.assertNotIn("misconception_graph", module)
        self.assertNotIn("adaptive_retrieval", module)


if __name__ == "__main__":
    unittest.main()
