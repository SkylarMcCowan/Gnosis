"""PROPOSAL: the only thing this pipeline ever does with a generation
result, pass or fail - write it to disk under `gnosis_workspace/proposals/`
for a human to read. Never registers anything into tool_registry or
skill_registry; "generated code does NOT immediately become production
code" (the roadmap's own words) is enforced by this being structurally the
end of the line.
"""
import os
from datetime import datetime

from core import config as core_config


def write_proposal(gap_finding, module_name, class_name, skill_code, test_rel_path, test_code, passed, output,
                    reviews=None, recommendation=None):
    """Returns the proposal's id (also its directory name under
    gnosis_workspace/proposals/). `reviews`/`recommendation` are Phase 11's
    engineering-team panel output (reviewers.panel.run_review_panel,
    reviewers.release_manager.summarize_reviews) - optional so this stays
    callable without them, but the real pipeline always supplies both."""
    proposal_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{module_name}"
    proposal_dir = core_config.path("gnosis_workspace", "proposals", proposal_id)
    os.makedirs(proposal_dir, exist_ok=True)

    with open(os.path.join(proposal_dir, f"{module_name}.py"), "w", encoding="utf-8") as f:
        f.write(skill_code)
    with open(os.path.join(proposal_dir, os.path.basename(test_rel_path)), "w", encoding="utf-8") as f:
        f.write(test_code)

    status = "PASSED - tests succeeded in the sandbox" if passed else "FAILED - see output below"
    gap_summary = gap_finding.get("summary", str(gap_finding)) if isinstance(gap_finding, dict) else str(gap_finding)
    review_section = ""
    if reviews:
        review_section = (
            "\n## Engineering team review (informational only)\n"
            f"- Security: {reviews.get('security', 'n/a')}\n"
            f"- Performance: {reviews.get('performance', 'n/a')}\n"
            f"- Documentation: {reviews.get('documentation', 'n/a')}\n"
            f"- Release Manager: {recommendation or 'n/a'}\n"
        )
    report = (
        f"# Tool-generation proposal {proposal_id}\n\n"
        f"## Capability gap\n{gap_summary}\n\n"
        f"## Generated skill\n`{module_name}.py`, class `{class_name}`\n\n"
        f"## Validation: {status}\n\n```\n{output}\n```\n"
        f"{review_section}\n"
        "## Review checklist (nothing here has been registered automatically)\n"
        "- [ ] Read the generated skill's execute() - does it only call tools it plausibly should?\n"
        "- [ ] Read the generated test - does it actually verify meaningful behavior, not just that "
        "nothing crashed?\n"
        "- [ ] If this looks good, register it by hand in webagent.py's _register_skills()\n"
    )
    with open(os.path.join(proposal_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    return proposal_id
