"""Deterministic learning-coach decisions.

The conversational skill lives in SKILL.md. This package is the regression
oracle for evidence, course-policy, citation, tutoring steps, and replanning.
It does not teach, call a model, or read private learner files.
"""

from coach.decisions import (
    accept_state,
    citation_decision,
    classify_evidence,
    load_legacy_markdown,
    migrate_v0_to_v1,
    next_tutor_action,
    normalize_signals,
    policy_gate,
    qualifies_as_prior_independent,
    replan,
    resolve_policy,
)

__all__ = [
    "accept_state",
    "citation_decision",
    "classify_evidence",
    "load_legacy_markdown",
    "migrate_v0_to_v1",
    "next_tutor_action",
    "normalize_signals",
    "policy_gate",
    "qualifies_as_prior_independent",
    "replan",
    "resolve_policy",
]
