"""Ties CAPABILITY GAP → DESIGN → GENERATE → GENERATE TESTS → SANDBOX →
RUN TESTS → PROPOSAL together - Phase 9's own pipeline diagram, minus a
separate CRITIC stage (Phase 6's critic is the *trigger*, not a second
pass over the generated code - see builder/__init__.py) and BENCHMARK (no
real metric exists yet beyond pass/fail).

Also runs Phase 11's engineering-team review panel over a generated skill
that made it to validation, same informational-only stance as
run_self_improve_cycle's - see reviewers/__init__.py.
"""
from core.events import events, SKILL_CREATED
from learning.critic import critique_recent_failures
from memory.experience import build_experience, record_experience
from builder.code_generator import generate_skill_for_gap
from builder.proposals import write_proposal
from builder.test_generator import generate_tests_for_skill
from builder.validator import validate_generated_skill
from reviewers.panel import run_review_panel
from reviewers.release_manager import summarize_reviews

_PIPELINE_AGENT = "tool-generator"


def run_tool_generation_cycle(coding_chat_fn, repo_root, available_tools, agent=None, window=10):
    """Returns a human-readable report string. Every branch records its
    own Phase 5 Experience, same discipline as run_self_improve_cycle -
    this agent's own history is what future critic/evaluator calls over
    `agent="tool-generator"` would read. Only ever writes a proposal to
    disk (see builder/proposals.py) - never registers anything, regardless
    of outcome."""
    def _record(goal, success, result):
        record_experience(build_experience(goal=goal, success=success, result=result, agent=_PIPELINE_AGENT))

    findings = critique_recent_failures(agent=agent, window=window)
    if not findings:
        report = "No recurring capability gap found in recent history - nothing to generate."
        _record("Generate a tool for a capability gap", None, report)
        return report

    finding = findings[0]  # critique_recent_failures already ranks most-frequent first
    goal = f"Generate a tool for: {finding['summary']}"

    module_name, class_name, skill_code, reason = generate_skill_for_gap(finding, coding_chat_fn, available_tools)
    if skill_code is None:
        report = f"No skill generated: {reason}."
        _record(goal, False, report)
        return report

    test_rel_path, test_code, reason = generate_tests_for_skill(module_name, class_name, skill_code, coding_chat_fn)
    if test_code is None:
        report = f"No tests generated: {reason}."
        _record(goal, False, report)
        return report

    passed, output = validate_generated_skill(repo_root, skill_code, test_rel_path, test_code)
    reviews = run_review_panel(skill_code, coding_chat_fn)
    recommendation = summarize_reviews(reviews.values(), tests_passed=passed)
    proposal_id = write_proposal(
        finding, module_name, class_name, skill_code, test_rel_path, test_code, passed, output,
        reviews=reviews, recommendation=recommendation,
    )
    events.publish(SKILL_CREATED, module_name=module_name, class_name=class_name, passed=passed)

    report = (
        f"Capability gap: {finding['summary']}\n"
        f"Generated skill '{class_name}' ({module_name}.py) - "
        f"{'tests passed' if passed else 'tests FAILED'} in the sandbox.\n"
        f"Engineering team recommendation: {recommendation}\n"
        f"Written as proposal '{proposal_id}' under gnosis_workspace/proposals/ - "
        "never registered automatically. Review before using."
    )
    _record(goal, passed, report)
    return report
