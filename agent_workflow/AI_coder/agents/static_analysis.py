"""Static analysis role and graph node."""
from ..contracts import Role
from ..nodes import execute_role


ROLE = Role(
    name='static',
    instructions="""
Inspect Python source and unit tests using configured check-only tools. Execute
every supplied static check with run_check. Do not execute unit tests, format,
edit, install tools or suppress findings. Report unavailable configuration as
blocked. Distinguish pre-existing findings from new implementation defects.
""",
)


def static_analysis_node(state, runner, root):
    """Run this role in its own model conversation and return its result through graph state."""
    return execute_role(ROLE, state, runner, root)
