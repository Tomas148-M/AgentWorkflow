"""Required human decision, validation and audit record."""
import json

from langgraph.types import interrupt

from ..runtime import fingerprint


def human_review_node(state, root, output):
    """Pause for a human decision and record only a valid explicit response."""
    # No side effects before interrupt: this node restarts on resume.
    payload = {
        "run_id": state["run_id"],
        "iteration": state["iteration"],
        "status": state["status"],
        "review_package": str(output / "review_package.json"),
        "decisions": ["approve", "request_changes", "reject"],
        "requires_limitations_acknowledgment": state["status"] != "checks_passed",
    }
    while True:
        answer = interrupt(payload)
        error = None
        if not isinstance(answer, dict) or answer.get("decision") not in {"approve", "request_changes", "reject"}:
            error = "Invalid human decision"
        elif answer["decision"] == "approve" and fingerprint(root) != state["check_state"]:
            error = "Source changed since checks; request_changes is required"
        elif answer["decision"] == "approve" and state["status"] != "checks_passed" and answer.get("acknowledge_limitations") is not True:
            error = "Explicit acknowledgment of unresolved limitations required"
        elif answer["decision"] == "request_changes" and not str(answer.get("feedback", "")).strip():
            error = "Change requests require feedback"
        if error is None:
            break
        payload = {**payload, "error": error}
    decision = answer["decision"]
    if decision == "approve":
        status = "approved" if state["status"] == "checks_passed" else "approved_with_limitations"
    elif decision == "reject":
        status = "rejected"
    else:
        status = "repair_requested" if state["iteration"] < 3 else "changes_required_new_run"
    record = {"run_id": state["run_id"], "iteration": state["iteration"], **answer, "status": status}
    text = "# Human review\n\n```json\n" + json.dumps(record, indent=2) + "\n```\n"
    (output / "human_review.md").write_text(text, encoding="utf-8")
    (output / f"iteration-{state['iteration']}-human_review.md").write_text(text, encoding="utf-8")
    return {"status": status, "human_feedback": answer.get("feedback", "")}
