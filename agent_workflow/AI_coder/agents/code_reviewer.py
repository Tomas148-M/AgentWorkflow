"""Code reviewer role and graph node."""
from ..contracts import Role
from ..nodes import execute_role


ROLE = Role(
    name='reviewer',
    report='code_review_notes.md',
    instructions="""
Read task, analysis and implementation report, then inspect actual source and
unit-test changes. Review correctness, safety, regressions and maintainability.
Report concrete findings by severity with file locations, reasons and fixes.
Do not treat style preferences as defects. Resolve prior findings explicitly.
Do not edit files. Return needs_changes for actionable implementation defects.
""",
)


def code_reviewer_node(state, runner, root, output):
    """Run this role in its own model conversation and save its report."""
    return execute_role(ROLE, state, runner, root, output)
