"""Tester role and graph node."""
from ..contracts import Role
from ..nodes import execute_role


ROLE = Role(
    name='tester',
    instructions="""
Independently verify acceptance criteria using the project's Python unit tests.
Inspect actual source and tests and run every configured unit-test command with
run_check. Evaluate assertions, boundary cases, errors, regressions and gaps.
Unit tests should isolate external systems with existing fixtures and mocks.
Do not edit files. Include commands, exit codes, counts, skips and untested
criteria. Zero collected tests is blocked, never a passing test run.
""",
)


def tester_node(state, runner, root):
    """Run this role in its own model conversation and return its result through graph state."""
    return execute_role(ROLE, state, runner, root)
