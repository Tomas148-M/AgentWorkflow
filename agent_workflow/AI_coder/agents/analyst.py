"""Analyst role and graph node."""
from ..contracts import Role
from ..nodes import execute_role


ROLE = Role(
    name='analyst',
    report='analyze.md',
    instructions="""
Analyze the task and actual repository. Identify requirements, acceptance criteria,
constraints, assumptions and risks. Recommend implementation and a Python unit-test
plan. Do not implement anything. Report unresolved questions explicitly.
""",
)


def analyst_node(state, runner, root, output):
    """Run this role in its own model conversation and save its report."""
    return execute_role(ROLE, state, runner, root, output)
