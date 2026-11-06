"""Start runs, inspect checkpoints, and submit explicit human decisions."""
import argparse
import json
import os
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .graph import build_graph
from .runtime import ModelRunner


def command(value):
    try:
        argv = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("Supply a JSON argv array") from error
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise argparse.ArgumentTypeError("Command must be a nonempty JSON array of strings")
    return argv


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = result.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start", help="Implement a task and pause for human review")
    task_input = start.add_mutually_exclusive_group(required=True)
    task_input.add_argument("--task", help="Task text passed directly into graph state")
    task_input.add_argument("--task-file", type=Path, help="Optional initial task import")
    start.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    start.add_argument("--static-command", action="append", type=command, default=[])
    start.add_argument("--test-command", action="append", type=command, default=[])
    resume = sub.add_parser("review", help="Resume a paused run with a human decision")
    resume.add_argument("run_id")
    resume.add_argument("--decision", required=True, choices=["approve", "request_changes", "reject"])
    resume.add_argument("--feedback", default="")
    resume.add_argument("--acknowledge-limitations", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("run_id")
    export = sub.add_parser("graph", help="Export actual graph as Mermaid")
    export.add_argument("--output", type=Path, default=Path("agents.mmd"))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        root = args.workspace.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace must be a directory")
        if args.action == "graph":
            from langgraph.checkpoint.memory import InMemorySaver
            graph = build_graph(None, root, InMemorySaver())
            args.output.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
            print(args.output)
            return 0
        if args.action == "start":
            from agent_workflow.backends import OpenAIBackend

            # Validate credentials before creating a run.
            backend = OpenAIBackend(args.model)
            task = args.task if args.task is not None else args.task_file.read_text(encoding="utf-8-sig")
            if not task.strip():
                raise ValueError("Task file is empty")
            run_id = uuid.uuid4().hex
            output = root / ".ai-coder" / "outputs" / run_id
            output.mkdir(parents=True)
            settings = {"model": args.model, "static_commands": args.static_command,
                        "test_commands": args.test_command}
            (output / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        else:
            run_id = args.run_id
            if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
                raise ValueError("Invalid run ID")
            output = root / ".ai-coder" / "outputs" / run_id
            settings = json.loads((output / "settings.json").read_text(encoding="utf-8"))
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
        with SqliteSaver.from_conn_string(str(output / "checkpoints.sqlite")) as saver:
            # status/approval/rejection do not require API credentials.
            needs_model = args.action == "start" or (args.action == "review" and args.decision == "request_changes")
            if args.action != "start" and needs_model:
                from agent_workflow.backends import OpenAIBackend

                backend = OpenAIBackend(settings["model"])
            runner = ModelRunner(backend, root, settings["static_commands"], settings["test_commands"]) if needs_model else None
            graph = build_graph(runner, root, saver)
            if args.action == "start":
                print(f"Run: {run_id}\nCheckpoint directory: {output}", flush=True)
                graph.invoke({"run_id": run_id, "task": task, "iteration": 0,
                              "reports": {}, "human_feedback": ""}, config)
            elif args.action == "review":
                snapshot = graph.get_state(config)
                if snapshot.next != ("human_review",):
                    raise ValueError("Run is not awaiting human review")
                graph.invoke(Command(resume={"decision": args.decision, "feedback": args.feedback,
                                             "acknowledge_limitations": args.acknowledge_limitations}), config)
            snapshot = graph.get_state(config)
            print(json.dumps({"run_id": run_id, "status": snapshot.values.get("status"),
                              "next": snapshot.next, "results": snapshot.values.get("reports", {}),
                              "summary": snapshot.values.get("summary"),
                              "human_decision": snapshot.values.get("human_review"),
                              "human_review": [i.value for task in snapshot.tasks for i in task.interrupts]}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"AI coder: {error}")
        return 1
