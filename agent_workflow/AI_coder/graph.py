"""Sequential coding graph with bounded repair and durable human interrupts."""
from functools import partial
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agents.analyst import analyst_node
from .agents.developer import developer_node
from .agents.code_reviewer import code_reviewer_node
from .agents.static_analysis import static_analysis_node
from .agents.tester import tester_node
from .agents.human_review import human_review_node

from .roles import ROLES
from .runtime import fingerprint


class CoderState(TypedDict, total=False):
    run_id: str
    task: str
    iteration: int
    reports: dict
    history: list[dict]
    review_package: dict
    human_review: dict
    human_reviews: list[dict]
    summary: dict
    human_feedback: str
    status: str
    source_state: str
    check_state: str


def build_graph(runner, root: Path, checkpointer):
    """Inject a role runner for live execution or deterministic offline tests."""
    root = Path(root)

    def evaluate(state):
        reports = state["reports"]
        statuses = [r["status"] for r in reports.values()]
        stale = fingerprint(root) != state["check_state"]
        if stale or "blocked" in statuses:
            status = "blocked"
        elif "needs_changes" in statuses:
            status = "failed"
        else:
            status = "checks_passed"
        package = {
            "run_id": state["run_id"], "task": state["task"],
            "iteration": state["iteration"], "status": status,
            "reports": reports, "source_state": state["check_state"],
            "source_changed_during_checks": stale,
        }
        return {"status": status, "review_package": package}

    def route_checks(state):
        return "developer" if state["status"] == "failed" and state["iteration"] < 3 else "human_review"


    def finish(state):
        return {"summary": {
            "run_id": state["run_id"], "status": state["status"],
            "results": {name: result["status"] for name, result in state["reports"].items()},
            "human_review": state["human_review"],
        }}

    builder = StateGraph(CoderState)
    builder.add_node("analyst", partial(analyst_node, runner=runner, root=root))
    builder.add_node("developer", partial(developer_node, runner=runner, root=root))
    builder.add_node("reviewer", partial(code_reviewer_node, runner=runner, root=root))
    builder.add_node("static", partial(static_analysis_node, runner=runner, root=root))
    builder.add_node("tester", partial(tester_node, runner=runner, root=root))
    builder.add_node("evaluate", evaluate)
    builder.add_node("human_review", partial(human_review_node, root=root))
    builder.add_node("finish", finish)
    chain = [START, *ROLES, "evaluate"]
    for left, right in zip(chain, chain[1:]):
        builder.add_edge(left, right)
    builder.add_conditional_edges("evaluate", route_checks, ["developer", "human_review"])
    builder.add_conditional_edges("human_review", lambda s: "developer" if s["status"] == "repair_requested" else "finish",
                                  ["developer", "finish"])
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)
