"""Developer role and graph node."""
from ..contracts import Role
from ..nodes import execute_role


ROLE = Role(
    name='developer',
    instructions="""
Implement the task and meaningful Python unit tests. Inspect existing source,
tests, repository guidance and pyproject.toml first. Follow supported Python
versions, naming, formatting and typing conventions. Prefer standard-library
solutions and small cohesive functions. Avoid mutable defaults and hidden state.
Use specific exceptions, context managers, portable paths, safe subprocess argv,
and parameterized queries. Never embed secrets or expose them in logs.
Preserve unrelated changes and API compatibility unless the task requires changes.
Address current-run review, static, test and human feedback. Document changed
files, behavior, assumptions and actual validation. Do not claim checks you did
not run. Only this role can write source and tests; final approval is human.
""",
)


def developer_node(state, runner, root):
    """Run this role in its own model conversation and return its result through graph state."""
    return execute_role(ROLE, state, runner, root)
