"""Ordered role registry; edit individual prompts in agents/*.py."""
from .contracts import CONTRACT, Role
from .agents.analyst import ROLE as ANALYST
from .agents.developer import ROLE as DEVELOPER
from .agents.code_reviewer import ROLE as REVIEWER
from .agents.static_analysis import ROLE as STATIC
from .agents.tester import ROLE as TESTER

ROLES = {role.name: role for role in (ANALYST, DEVELOPER, REVIEWER, STATIC, TESTER)}
