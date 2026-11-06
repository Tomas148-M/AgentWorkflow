"""Shared report persistence and source-state tracking for agent nodes."""
from .runtime import fingerprint


def execute_role(role, state, runner, root, output):
    """Execute an isolated role while preserving current-run feedback."""
    name = role.name
    iteration = state.get("iteration", 0) + (name == "developer")
    reports = dict(state.get("reports", {}))
    # Feedback must reach the developer before obsolete reports are cleared.
    before = fingerprint(root)
    result = runner(name, {**state, "iteration": iteration})
    after = fingerprint(root)
    if name != "developer" and after != before:
        result = {
            "status": "blocked",
            "report": "Repository changed during a read-only role.\n" + result["report"],
        }
    if name == "developer":
        reports = {key: value for key, value in reports.items() if key == "analyst"}
    reports[name] = {**result, "iteration": iteration, "source_state": after}
    text = (
        f"# {name}\n\nRun: {state['run_id']}\nIteration: {iteration}\n"
        f"Source SHA256: {after}\nStatus: {result['status']}\n\n{result['report']}\n"
    )
    (output / role.report).write_text(text, encoding="utf-8")
    (output / f"iteration-{iteration}-{role.report}").write_text(text, encoding="utf-8")
    update = {"reports": reports, "iteration": iteration, "source_state": after}
    if name == "developer":
        update["check_state"] = after
        update["status"] = "checking"
    return update
