"""Decision rules for evidence, policy, citations, tutoring steps, and replans.

Inputs are data. This module does not fetch course policies, open textbooks,
or read ~/Self-Study. A missing page, policy, or submission status stays missing.
"""

from __future__ import annotations

from datetime import datetime

LADDER = ("未测", "已接触", "辅助完成", "独立完成", "延迟保持")
ASSISTED = ("hint", "worked_example", "answer_shown", "external")
SIGNAL_SYSTEMS = ("canvas", "joj", "git")
SIGNAL_STATUSES = ("submitted", "missing", "unknown", "conflicting")
ALLOWANCE_KEYS = (
    "general_concepts",
    "policy_clarification",
    "hints_without_solution",
    "analogous_examples",
    "graded_answers",
)


def classify_evidence(record):
    """Map one performance record onto the existing five-level ladder.

    Hinted or otherwise assisted success stays at 辅助完成. Independent
    mastery requires an observed, unassisted success on an unseen transfer.
    延迟保持 additionally requires a later local calendar day and a different
    task that itself meets the independent bar. Self-report never rises above
    已接触.
    """
    source = record.get("source_kind")
    assistance = record.get("assistance")
    performance = record.get("performance")
    result = {
        "ladder": "未测",
        "independent_mastery": False,
        "delayed_retention": False,
        "reasons": [],
        "source_kind": source,
        "assistance": assistance,
        "timestamp": record.get("timestamp"),
        "task_id": record.get("task_id"),
        "invented_observation": False,
    }
    missing = [
        key
        for key in ("source_kind", "assistance", "performance")
        if record.get(key) in (None, "")
    ]
    if missing:
        result["reasons"].append("required_field_missing:" + ",".join(missing))
        return result
    if source not in ("self_report", "observed"):
        result["reasons"].append("source_kind_unknown")
        return result
    if performance not in ("successful", "unsuccessful", "attempted"):
        result["reasons"].append("performance_unknown")
        return result
    if source == "self_report":
        if performance == "successful":
            result["ladder"] = "已接触"
            result["reasons"].append("self_report_is_not_observed_performance")
        else:
            result["reasons"].append("self_report_without_success")
        return result
    if performance != "successful":
        if assistance in ASSISTED or record.get("taught") is True:
            result["ladder"] = "已接触"
        result["reasons"].append("observed_without_success")
        return result
    if assistance in ASSISTED:
        result["ladder"] = "辅助完成"
        result["reasons"].append("assisted_success_is_not_independent_mastery")
        return result
    if assistance != "none":
        result["ladder"] = "辅助完成"
        result["reasons"].append("unrecognized_assistance_treated_as_assisted")
        return result
    if _aware(record.get("timestamp")) is None:
        result["ladder"] = "已接触"
        result["reasons"].append("timestamp_required_for_independent_claim")
        return result
    unseen = record.get("seen_before") is False and record.get("transfer") is True
    if not unseen:
        result["ladder"] = "已接触"
        result["observed_unassisted_success"] = True
        result["reasons"].append("unseen_transfer_required_for_independent_mastery")
        return result
    delayed, delay_reason = _delayed(
        record.get("timestamp"),
        record.get("task_id"),
        record.get("prior_independent"),
        record.get("skill"),
    )
    result["independent_mastery"] = True
    result["reasons"].append("independent_unseen_transfer")
    if delayed:
        result["ladder"] = "延迟保持"
        result["delayed_retention"] = True
        result["reasons"].append("later_local_date_retention")
    else:
        result["ladder"] = "独立完成"
        if record.get("prior_independent") is not None and delay_reason:
            result["reasons"].append(delay_reason)
    return result


def _nonempty_skill(value):
    return isinstance(value, str) and bool(value.strip())


def _prior_provenance_ok(entry):
    """Same bar for a full evidence record and a compact projection.

    A ladder label, an unseen flag, or a legacy cell is not enough. Hinted
    help, a legacy projection, a missing observation, or a missing skill fails.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("legacy_projection") is True:
        return False
    if entry.get("assistance") != "none":
        return False
    if entry.get("source_kind") != "observed":
        return False
    if not _nonempty_skill(entry.get("skill")):
        return False
    if _aware(entry.get("timestamp")) is None or not entry.get("task_id"):
        return False
    if any(key in entry for key in ("performance", "seen_before", "transfer")):
        return (
            entry.get("performance") == "successful"
            and entry.get("seen_before") is False
            and entry.get("transfer") is True
        )
    return (
        entry.get("unseen_transfer") is True
        and entry.get("ladder") in ("独立完成", "延迟保持")
    )


def qualifies_as_prior_independent(entry, skill=None):
    """True only when entry itself is an observed unassisted unseen success.

    Passing skill requires that same nonempty skill on the entry. A missing
    skill is not filled in, and a legacy projection never qualifies.
    """
    if not _prior_provenance_ok(entry):
        return False
    if skill is None:
        return True
    if not _nonempty_skill(skill):
        return False
    return entry.get("skill").strip() == skill.strip()


def _delayed(timestamp, task_id, prior, skill):
    if not isinstance(prior, dict):
        return False, "delayed_retention_requires_prior_independent"
    if not _nonempty_skill(skill) or not _nonempty_skill(prior.get("skill")):
        return False, "delayed_retention_requires_skill"
    if prior.get("skill").strip() != skill.strip():
        return False, "delayed_retention_requires_same_skill"
    if not qualifies_as_prior_independent(prior, skill=skill):
        return False, "prior_was_not_independent_unseen_transfer"
    prior_task = prior.get("task_id")
    if not prior_task or not task_id or prior_task == task_id:
        return False, "delayed_check_requires_a_different_task"
    earlier = _local_date(prior.get("timestamp"))
    later = _local_date(timestamp)
    if earlier is None or later is None:
        return False, "timezone_required_for_delayed_retention"
    if later <= earlier:
        return False, "delayed_retention_requires_a_later_local_date"
    return True, None


def resolve_policy(policy):
    """Return the policy actually on record. Never fill in a statement.

    The result is safe to store and resolve again: a verified statement keeps
    statement_present and the recorded True/False allowances. A verified flag
    without statement text stays unknown and does not become verified later.
    """
    empty = {key: None for key in ALLOWANCE_KEYS}

    def pack(status, statement, present, allowances, reason):
        return {
            "status": status,
            "statement": statement,
            "statement_present": present,
            "allowances": dict(allowances),
            "reason": reason,
            "invented_policy": False,
        }

    if not isinstance(policy, dict):
        return pack("unknown", None, False, empty, "policy_absent")
    status = policy.get("status")
    statement = policy.get("statement")
    text = statement.strip() if isinstance(statement, str) and statement.strip() else None
    present = policy.get("statement_present") is True and text is not None
    raw = policy.get("allowances") if isinstance(policy.get("allowances"), dict) else {}
    allowances = {}
    for key in ALLOWANCE_KEYS:
        if key in raw and isinstance(raw[key], bool):
            allowances[key] = raw[key]
        else:
            allowances[key] = None
    if status == "conflicting":
        return pack("conflicting", None, False, empty, "policy_reports_conflict")
    if status == "verified" and present:
        return pack("verified", text, True, allowances, "statement_recorded")
    if status == "verified" or policy.get("reason") == "verified_flag_without_recorded_statement":
        return pack("unknown", None, False, empty, "verified_flag_without_recorded_statement")
    if policy.get("reason") == "policy_absent":
        return pack("unknown", None, False, empty, "policy_absent")
    return pack("unknown", None, False, empty, "policy_unknown")


def policy_gate(policy, request_kind, distinct_from_graded_item=False):
    """Decide whether a kind of help is available.

    Unknown, conflicting, or unverifiable policy: general concepts and policy
    clarification stay available. Assignment hints and analogous examples do
    not. A missing allowance is not a permission. Graded work is never emitted,
    including when a verified allowance says answers are permitted.
    """
    resolved = resolve_policy(policy)
    base = {
        "policy_status": resolved["status"],
        "invented_policy": False,
        "policy_statement_used": resolved["statement"] if resolved["status"] == "verified" else None,
        "coach_emits_graded_solution": False,
        "request_kind": request_kind,
    }
    if request_kind == "policy_clarification":
        return {**base, "allow": True, "reason": "ask_for_the_actual_policy"}
    if request_kind == "general_concept":
        if resolved["allowances"].get("general_concepts") is False:
            return {**base, "allow": False, "reason": "verified_policy_disallows_general_concepts"}
        return {**base, "allow": True, "reason": "general_concepts_allowed"}
    if request_kind in ("graded_answer", "submission_draft"):
        recorded = resolved["allowances"].get("graded_answers")
        return {
            **base,
            "allow": False,
            "reason": "coach_does_not_complete_graded_work",
            "course_policy_allows_graded_answers": recorded if resolved["status"] == "verified" else None,
            "course_policy_forbids_graded_answers": (recorded is False) if resolved["status"] == "verified" else None,
        }
    if request_kind == "hint_without_solution":
        if resolved["status"] != "verified" or resolved["allowances"].get("hints_without_solution") is not True:
            return {**base, "allow": False, "reason": "assignment_hint_requires_verified_allowance"}
        return {**base, "allow": True, "reason": "hint_without_solution"}
    if request_kind == "analogous_example":
        if distinct_from_graded_item is not True:
            return {**base, "allow": False, "reason": "analogous_example_must_be_a_different_item"}
        if resolved["status"] != "verified" or resolved["allowances"].get("analogous_examples") is not True:
            return {**base, "allow": False, "reason": "analogous_example_requires_verified_allowance"}
        return {
            **base,
            "allow": True,
            "reason": "analogous_example_excludes_graded_item",
            "graded_item_excluded": True,
        }
    return {**base, "allow": False, "reason": "unknown_request_denied"}


def citation_decision(source):
    """Cite a location or page only when this record says it was verified.

    Does not look up a book and does not invent a page when `page` is empty.
    Unverified text is withheld from the citable fields.
    """
    if not isinstance(source, dict):
        source = {}
    status = source.get("status")
    location = _clean_text(source.get("location"))
    page = _clean_text(source.get("page"))
    if status != "verified":
        return {
            "may_cite_location": False,
            "may_cite_page": False,
            "location_used": None,
            "page_used": None,
            "reason": "not_verified" if status in ("unverified", "unknown") else "status_unknown",
            "invented_location": False,
            "invented_page": False,
        }
    return {
        "may_cite_location": location is not None,
        "may_cite_page": page is not None,
        "location_used": location,
        "page_used": page,
        "reason": "verified" if location or page else "verified_but_no_location_recorded",
        "invented_location": False,
        "invented_page": False,
    }


def next_tutor_action(session):
    """Return the next tutoring step. Never marks mastery and never emits a solution.

    Graded work needs a verified policy before any assignment-specific hint.
    Until then the only help is a general concept or a request for the policy
    text, including when the session is labeled self_study. Self-study still
    gives a full explanation when the learner asks and the item is not graded;
    that records answer_shown.
    """
    if not isinstance(session, dict):
        session = {}
    mode = session.get("mode")
    resolved = resolve_policy(session.get("policy"))
    if mode not in ("self_study", "formal_course"):
        return _action("reject_unknown_mode", "none", resolved)
    graded = session.get("graded") is True
    request = session.get("learner_request") or "continue"
    attempt = session.get("attempt_submitted") is True
    try:
        layer = int(session.get("hints_already") or 0)
    except (TypeError, ValueError):
        layer = 0
    if layer < 0:
        layer = 0
    teachback_done = session.get("teachback_done") is True
    transfer_assigned = session.get("transfer_assigned") is True

    if graded and request in ("answer", "submission"):
        extra = {}
        if resolved["status"] != "verified":
            extra["follow_up"] = "request_policy"
        else:
            extra["course_policy_allows_graded_answers"] = resolved["allowances"].get("graded_answers")
            if resolved["allowances"].get("general_concepts") is False:
                extra["follow_up"] = "stop_and_wait"
            else:
                extra["follow_up"] = "explain_general_concept"
        return _action("refuse_graded_completion", "none", resolved, **extra)
    if request == "policy":
        return _action("request_policy", "none", resolved)
    if request == "concept":
        gate = policy_gate(session.get("policy"), "general_concept")
        if not gate["allow"]:
            return _action("request_policy", "none", resolved, reason=gate["reason"])
        return _action("explain_general_concept", "none", resolved, graded_item_excluded=True)
    if mode == "self_study" and not graded and request == "answer":
        return _action("fuller_explanation", "answer_shown", resolved)
    if not attempt and request in ("hint", "explain", "continue", "answer"):
        return _action("restate_attempt", "none", resolved)
    if teachback_done and not transfer_assigned:
        return _action(
            "assign_unseen_transfer",
            "none",
            resolved,
            transfer_must_be_unseen=True,
            not_the_graded_submission=True,
            graded_item_excluded=True,
        )
    if teachback_done and transfer_assigned:
        return _action("stop_and_wait", "none", resolved, reason="wait_for_unseen_transfer_attempt")
    sequence = _hint_sequence(graded, session.get("policy"))
    if layer < len(sequence):
        action = sequence[layer]
        assistance = _assistance_for(action, graded)
        return _action(
            action,
            assistance,
            resolved,
            layer_index=layer,
            graded_item_excluded=action in ("analogous_example", "explain_general_concept"),
        )
    reason = "no_further_help_without_completing_graded_work" if graded else "wait_for_learner"
    return _action("stop_and_wait", "none", resolved, reason=reason)


def _hint_sequence(graded, policy):
    if not graded:
        return [
            "orient_concept",
            "strategic_hint",
            "partial_structure",
            "analogous_example",
            "request_teachback",
        ]
    resolved = resolve_policy(policy)
    hints_allowed = policy_gate(policy, "hint_without_solution")["allow"]
    analogy_allowed = policy_gate(policy, "analogous_example", distinct_from_graded_item=True)["allow"]
    concepts_allowed = policy_gate(policy, "general_concept")["allow"]
    if not hints_allowed:
        if not concepts_allowed:
            return ["request_policy"]
        if resolved["status"] != "verified":
            return ["request_policy", "explain_general_concept"]
        return ["explain_general_concept", "request_teachback"]
    sequence = ["orient_concept", "strategic_hint", "partial_structure"]
    if analogy_allowed:
        sequence.append("analogous_example")
    sequence.append("request_teachback")
    return sequence


def _assistance_for(action, graded):
    if action == "analogous_example":
        return "worked_example"
    if action in ("orient_concept", "strategic_hint", "partial_structure"):
        return "hint"
    return "none"


def _action(action, assistance, resolved, **extra):
    body = {
        "action": action,
        "assistance": assistance,
        "counts_as_independent_mastery": False,
        "emits_graded_solution": False,
        "invented_policy": False,
        "policy_status": resolved["status"],
    }
    body.update(extra)
    return body


def normalize_signals(signals):
    """Read each submission system separately.

    A missing Canvas status does not write JOJ or Git. An omitted system is
    unknown, not missing.
    """
    signals = signals if isinstance(signals, dict) else {}
    out = {}
    for system in SIGNAL_SYSTEMS:
        out[system] = {
            "status": _signal_status(signals.get(system, None) if system in signals else None),
            "implied_by_other_system": False,
        }
    return out


def _signal_status(raw):
    if raw is None:
        return "unknown"
    if isinstance(raw, str):
        return raw if raw in SIGNAL_STATUSES else "unknown"
    if isinstance(raw, dict):
        if "reports" in raw:
            cleaned = [item for item in raw.get("reports") or [] if item in ("submitted", "missing", "unknown")]
            distinct = set(cleaned)
            if len(distinct) > 1:
                return "conflicting"
            if len(distinct) == 1:
                return cleaned[0]
            return "unknown"
        if "status" in raw:
            return _signal_status(raw.get("status"))
    return "unknown"


def replan(payload):
    """Order courses and fit unfinished work into contiguous blocks.

    Unknown and conflicting inputs stay labeled. Missed-session tasks are put
    back if the caller omitted them. Nothing is marked mastered. No deadline
    or submission status is invented.
    """
    payload = payload if isinstance(payload, dict) else {}
    conflicts = []
    unknowns = []
    courses = []
    for raw in payload.get("courses") or []:
        if not isinstance(raw, dict):
            continue
        course_id = raw.get("id")
        signals = normalize_signals(raw.get("signals"))
        deadline_status = raw.get("deadline_status")
        deadline = None
        if deadline_status not in ("known", "unknown", "conflicting"):
            deadline_status = "unknown"
            _note(unknowns, {"course_id": course_id, "field": "deadline_status"})
        if deadline_status == "known":
            if _aware(raw.get("deadline")) is None:
                deadline_status = "unknown"
                _note(unknowns, {
                    "course_id": course_id,
                    "field": "deadline",
                    "reason": "known_flag_without_timestamp",
                })
            else:
                deadline = raw.get("deadline")
        elif deadline_status == "conflicting":
            conflicts.append({
                "course_id": course_id,
                "field": "deadline",
                "reports": list(raw.get("deadline_reports") or []),
            })
        else:
            _note(unknowns, {"course_id": course_id, "field": "deadline"})
        for system, info in signals.items():
            if info["status"] == "unknown":
                _note(unknowns, {"course_id": course_id, "field": system})
            elif info["status"] == "conflicting":
                conflicts.append({"course_id": course_id, "field": system, "reports": _reports(raw.get("signals"), system)})
        tasks = []
        for task in raw.get("tasks") or []:
            if isinstance(task, dict) and task.get("id"):
                tasks.append(dict(task))
        courses.append({
            "id": course_id,
            "deadline_status": deadline_status,
            "deadline": deadline,
            "signals": signals,
            "tasks": tasks,
            "policy_status": raw.get("policy_status") if raw.get("policy_status") in ("unknown", "verified", "conflicting") else "unknown",
        })

    missed = payload.get("missed_session") if isinstance(payload.get("missed_session"), dict) else None
    if missed:
        course_id = missed.get("course_id")
        course = next((item for item in courses if item["id"] == course_id), None)
        if course is None:
            _note(unknowns, {"course_id": course_id, "field": "missed_session_course"})
            course = {
                "id": course_id,
                "deadline_status": "unknown",
                "deadline": None,
                "signals": normalize_signals({}),
                "tasks": [],
                "policy_status": "unknown",
            }
            courses.append(course)
            _note(unknowns, {"course_id": course_id, "field": "deadline"})
        existing = {task.get("id") for task in course["tasks"]}
        for task_id in missed.get("task_ids") or []:
            if task_id in existing:
                for task in course["tasks"]:
                    if task.get("id") == task_id:
                        task["from_missed_session"] = True
            else:
                course["tasks"].append({
                    "id": task_id,
                    "minutes": None,
                    "kind": "practice",
                    "required": True,
                    "from_missed_session": True,
                })

    def sort_key(course):
        blocked = sum(1 for task in course["tasks"] if task.get("blocked_by_gap"))
        required = sum(1 for task in course["tasks"] if task.get("required") is True)
        if course["deadline_status"] == "known":
            return (0, _aware(course["deadline"]), -blocked, -required, str(course["id"]))
        if course["deadline_status"] == "unknown":
            return (1, "", -blocked, -required, str(course["id"]))
        return (2, "", -blocked, -required, str(course["id"]))

    ordered = sorted(courses, key=sort_key)
    usable, schedule_status, block_conflicts = _blocks(payload.get("blocks", None))
    conflicts.extend(block_conflicts)
    if schedule_status == "schedule_unknown":
        _note(unknowns, {"field": "blocks"})

    scheduled = []
    retained = []
    queue = _queue(ordered, retained)
    if schedule_status != "scheduled":
        for item in queue:
            _retain(retained, item["course_id"], item["task"], item["task"].get("minutes"), schedule_status)
    else:
        for item in queue:
            task = item["task"]
            minutes = _minutes(task.get("minutes"))
            if minutes is None:
                _retain(retained, item["course_id"], task, task.get("minutes"), "duration_unknown")
                continue
            used = _consume(scheduled, usable, item["course_id"], task, minutes)
            if used < minutes:
                reason = "partial_block" if used else "no_fitting_block"
                _retain(retained, item["course_id"], task, minutes - used, reason)

    present = {item["task_id"] for item in scheduled} | {item["task_id"] for item in retained}
    for course in ordered:
        for task in course["tasks"]:
            if task.get("id") not in present:
                _retain(retained, course["id"], task, task.get("minutes"), "retained_unscheduled")

    missed_out = None
    if missed:
        present = {item["task_id"] for item in scheduled} | {item["task_id"] for item in retained}
        missed_out = {
            "course_id": missed.get("course_id"),
            "when": missed.get("when"),
            "task_ids": list(missed.get("task_ids") or []),
            "dropped": False,
            "tasks_still_present": [
                {"task_id": task_id, "present": task_id in present}
                for task_id in missed.get("task_ids") or []
            ],
        }
    return {
        "ordered_course_ids": [course["id"] for course in ordered],
        "signals_by_course": {course["id"]: course["signals"] for course in ordered},
        "conflicts": conflicts,
        "unknowns": unknowns,
        "scheduled": scheduled,
        "retained_unscheduled": retained,
        "missed_session": missed_out,
        "schedule_status": schedule_status,
        "invented_deadline": False,
        "invented_submission": False,
        "mastery_updates": [],
        "policy_status_by_course": {course["id"]: course["policy_status"] for course in ordered},
    }


def _queue(courses, retained):
    queue = []
    for course in courses:
        for task in course["tasks"]:
            if task.get("kind") == "submission" and course["deadline_status"] == "conflicting":
                _retain(retained, course["id"], task, task.get("minutes"), "deadline_conflict")
                continue
            if task.get("kind") == "submission" and course["deadline_status"] != "known":
                _retain(retained, course["id"], task, task.get("minutes"), "deadline_unknown")
                continue
            gap = task.get("blocked_by_gap")
            if gap and task.get("gap_ladder") not in ("独立完成", "延迟保持"):
                gap_task = {
                    "id": "gap:{0}:{1}".format(gap, task.get("id")),
                    "minutes": task.get("gap_minutes") if isinstance(task.get("gap_minutes"), int) else None,
                    "kind": "gap_study",
                    "required": True,
                    "from_missed_session": False,
                }
                if gap_task["minutes"] is None:
                    _retain(retained, course["id"], gap_task, None, "gap_duration_unknown")
                    _retain(retained, course["id"], task, task.get("minutes"), "blocked_gap_duration_unknown")
                    continue
                queue.append({"course_id": course["id"], "task": gap_task})
            queue.append({"course_id": course["id"], "task": task})
    return queue


def _blocks(blocks):
    if blocks is None:
        return [], "schedule_unknown", []
    if not isinstance(blocks, list):
        return [], "schedule_unknown", [{"field": "blocks", "reason": "unreadable"}]
    parsed = []
    conflicts = []
    for block in blocks:
        if not isinstance(block, dict):
            conflicts.append({"field": "block", "reason": "unreadable"})
            continue
        start = _aware(block.get("start"))
        end = _aware(block.get("end"))
        if start is None or end is None or end <= start:
            conflicts.append({"field": "block", "id": block.get("id"), "reason": "invalid_interval"})
            continue
        parsed.append({
            "id": block.get("id"),
            "start": start,
            "end": end,
            "remaining": int((end - start).total_seconds() // 60),
        })
    parsed.sort(key=lambda block: block["start"])
    for earlier_index, earlier in enumerate(parsed):
        for later in parsed[earlier_index + 1:]:
            if earlier["start"] < later["end"] and later["start"] < earlier["end"]:
                conflicts.append({
                    "field": "blocks",
                    "ids": [earlier["id"], later["id"]],
                    "reason": "overlap",
                })
    if conflicts:
        return [], "block_conflict", conflicts
    if not parsed:
        return [], "no_available_block", []
    return parsed, "scheduled", []


def _consume(scheduled, blocks, course_id, task, minutes):
    left = minutes
    for block in blocks:
        if left <= 0:
            break
        if block["remaining"] <= 0:
            continue
        used = min(block["remaining"], left)
        block["remaining"] -= used
        left -= used
        scheduled.append({
            "course_id": course_id,
            "task_id": task.get("id"),
            "block_id": block["id"],
            "minutes": used,
            "kind": task.get("kind"),
            "completed": False,
        })
    return minutes - left


def _retain(retained, course_id, task, minutes, reason):
    retained.append({
        "course_id": course_id,
        "task_id": task.get("id"),
        "minutes": minutes,
        "kind": task.get("kind"),
        "reason": reason,
        "from_missed_session": task.get("from_missed_session") is True,
        "completed": False,
    })


def _reports(signals, system):
    if not isinstance(signals, dict):
        return []
    raw = signals.get(system)
    if isinstance(raw, dict):
        return list(raw.get("reports") or [])
    return []


def _note(items, note):
    if note not in items:
        items.append(note)


def _minutes(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _clean_text(value):
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _aware(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _local_date(value):
    parsed = _aware(value)
    if parsed is None:
        return None
    return parsed.date()


def load_legacy_markdown(text):
    """Read the v0 STATE.md subset. Unknown sections are kept."""
    text = text if isinstance(text, str) else ""
    sections = {}
    current = "_preamble"
    buffer = []

    def flush():
        sections[current] = "\n".join(buffer).strip("\n")

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)
    flush()
    fields = {}
    for line in sections.get("_preamble", "").splitlines():
        if line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            fields[key.strip()] = value.strip()
    mode = "self_study"
    if fields.get("模式") in ("self_study", "formal_course"):
        mode = fields["模式"]
    abilities = []
    for line in sections.get("能力表", "").splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        item = {}
        for part in line[2:].split("；"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            item[key.strip()] = value.strip()
        if "技能" in item:
            abilities.append(item)
    tasks = []
    for line in sections.get("待答问题", "").splitlines():
        if line.startswith("- "):
            tasks.append(line[2:].strip())
    retests = []
    for line in sections.get("待复测", "").splitlines():
        if line.startswith("- "):
            retests.append(line[2:].strip())
    return {
        "schema_read": "learning-coach.state/v0",
        "mode": mode,
        "course_id": fields.get("课程 ID"),
        "name": fields.get("名称"),
        "updated_at": fields.get("更新时间"),
        "abilities": abilities,
        "open_tasks": tasks,
        "retests": retests,
        "reading_task": sections.get("当前阅读任务", ""),
        "time_notes": sections.get("时间", ""),
        "sections": sections,
        "formal_policy_invented": False,
    }


def migrate_v0_to_v1(state, original_text):
    """Add v1 fields without deleting v0 sections, tasks, or ladder cells.

    Legacy ladder text is preserved even when it would not qualify as a new
    v1 claim. No evidence record is invented from it.
    """
    abilities = []
    conflicts = []
    for item in state.get("abilities") or []:
        level = item.get("等级")
        origin = item.get("来源") or ""
        source_kind = "unknown"
        if "自报" in origin:
            source_kind = "self_report"
        elif "观察" in origin or "诊断" in origin:
            source_kind = "observed"
        conflict = None
        if source_kind == "self_report" and level in ("独立完成", "延迟保持", "辅助完成"):
            conflict = "self_report_stored_as_" + level
            conflicts.append({"skill": item.get("技能"), "conflict": conflict})
        abilities.append({
            "skill": item.get("技能"),
            "ladder": level,
            "source_kind": source_kind,
            "legacy_projection": True,
            "stored_text": dict(item),
            "conflict": conflict,
            "use_for_new_independent_claim": False,
        })
    authority = {"role": "local", "store": "filesystem"}
    return {
        "schema": "learning-coach.state/v1",
        "mode": state.get("mode") or "self_study",
        "authority": authority,
        "course_id": state.get("course_id"),
        "name": state.get("name"),
        "updated_at": state.get("updated_at"),
        "abilities": abilities,
        "open_tasks": list(state.get("open_tasks") or []),
        "retests": list(state.get("retests") or []),
        "reading_task": state.get("reading_task") or "",
        "time_notes": state.get("time_notes") or "",
        "policy": None,
        "evidence_records": [],
        "preserved_sections": dict(state.get("sections") or {}),
        "original_text_retained": original_text,
        "dropped_sections": [],
        "conflicts": conflicts,
        "invented_policy": False,
        "invented_pages": False,
        "integrations_required": False,
    }


def _portable_sources(sources):
    """Copy source records without promoting an unverified location."""
    if not isinstance(sources, list):
        return []
    kept = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        status = source.get("status")
        if status not in ("verified", "unverified", "unknown"):
            status = "unknown"
        item = {"status": status}
        for key in ("id", "location", "page", "checked"):
            if key in source:
                item[key] = source.get(key)
        kept.append(item)
    return kept


def accept_state(document):
    """Accept v0 markdown or a v1 mapping. Keep exactly one authority."""
    if isinstance(document, str):
        loaded = load_legacy_markdown(document)
        return migrate_v0_to_v1(loaded, document)
    if not isinstance(document, dict):
        return {
            "schema": "learning-coach.state/v1",
            "mode": "self_study",
            "authority": {"role": "local", "store": "filesystem"},
            "open_tasks": [],
            "evidence_records": [],
            "unreadable": True,
            "invented_policy": False,
        }
    if document.get("schema") == "learning-coach.state/v1":
        mode = document.get("mode") if document.get("mode") in ("self_study", "formal_course") else "self_study"
        migrated = {
            "schema": "learning-coach.state/v1",
            "mode": mode,
            "course_id": document.get("course_id"),
            "open_tasks": list(document.get("open_tasks") or []),
            "retests": list(document.get("retests") or []),
            "abilities": list(document.get("abilities") or []),
            "evidence_records": list(document.get("evidence_records") or []),
            "preserved_sections": dict(document.get("preserved_sections") or {}),
            "policy": resolve_policy(document.get("policy")) if mode == "formal_course" else document.get("policy"),
            "invented_policy": False,
            "integrations_required": False,
        }
        if "sources" in document:
            migrated["sources"] = _portable_sources(document.get("sources"))
        if "signals" in document:
            migrated["signals"] = normalize_signals(document.get("signals"))
        authority = document.get("authority")
        if isinstance(authority, dict) and authority.get("role") in ("local", "notion"):
            migrated["authority"] = {"role": authority.get("role"), "store": authority.get("store")}
        else:
            migrated["authority"] = {"role": "local", "store": "filesystem"}
        return migrated
    wrapped = migrate_v0_to_v1(document, document.get("original_text_retained") or "")
    return wrapped
