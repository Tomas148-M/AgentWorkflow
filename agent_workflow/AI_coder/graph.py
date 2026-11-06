"""Sequential coding graph with bounded repair and durable human interrupts."""
import json
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
    human_feedback: str
    status: str
    source_state: str
    check_state: str


def build_graph(runner, root: Path, output: Path, checkpointer):
    """Inject a role runner for live execution or deterministic offline tests."""
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)

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
        package = {**state, "status": status, "source_changed_during_checks": stale}
        (output / "review_package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        return {"status": status}

    def route_checks(state):
        return "developer" if state["status"] == "failed" and state["iteration"] < 3 else "human_review"


    def finish(state):
        text = f"# Final outcome\n\nRun: {state['run_id']}\nStatus: {state['status']}\n"
        for role, report in state["reports"].items():
            text += f"\n- {role}: {report['status']} ({ROLES[role].report})"
        text += "\n\nSee human_review.md for the explicit human decision.\n"
        (output / "summary.md").write_text(text, encoding="utf-8")
        return {}

    builder = StateGraph(CoderState)
    builder.add_node("analyst", partial(analyst_node, runner=runner, root=root, output=output))
    builder.add_node("developer", partial(developer_node, runner=runner, root=root, output=output))
    builder.add_node("reviewer", partial(code_reviewer_node, runner=runner, root=root, output=output))
    builder.add_node("static", partial(static_analysis_node, runner=runner, root=root, output=output))
    builder.add_node("tester", partial(tester_node, runner=runner, root=root, output=output))
    builder.add_node("evaluate", evaluate)
    builder.add_node("human_review", partial(human_review_node, root=root, output=output))
    builder.add_node("finish", finish)
    chain = [START, *ROLES, "evaluate"]
    for left, right in zip(chain, chain[1:]):
        builder.add_edge(left, right)
    builder.add_conditional_edges("evaluate", route_checks, ["developer", "human_review"])
    builder.add_conditional_edges("human_review", lambda s: "developer" if s["status"] == "repair_requested" else "finish",
                                  ["developer", "finish"])
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)
