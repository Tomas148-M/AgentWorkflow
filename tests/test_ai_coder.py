import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from agent_workflow.AI_coder.graph import build_graph
    HAS_GRAPH = True
except ImportError:
    HAS_GRAPH = False

from agent_workflow.AI_coder.runtime import ModelRunner, Workspace


@unittest.skipUnless(HAS_GRAPH, "Install .[ai-coder] to test LangGraph")
class GraphTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / ".ai-coder" / "outputs" / "test"
        self.calls = []
        self.config = {"configurable": {"thread_id": "test"}, "recursion_limit": 100}

    def runner(self, role, state):
        self.calls.append((role, state["iteration"]))
        return {"status": "pass", "report": f"Examined {role}"}

    def start(self, graph):
        return graph.invoke({"run_id": "test", "task": "Test task", "reports": {},
                             "iteration": 0, "human_feedback": ""}, self.config)

    def test_human_interrupt_and_approval(self):
        graph = build_graph(self.runner, self.root, InMemorySaver())
        result = self.start(graph)
        self.assertIn("__interrupt__", result)
        self.assertFalse((self.output / "human_review.md").exists())
        result = graph.invoke(Command(resume={"decision": "approve"}), self.config)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["human_review"]["decision"], "approve")
        self.assertEqual(result["summary"]["status"], "approved")
        self.assertEqual(len(result["history"]), 5)
        self.assertFalse(self.output.exists())
        self.assertEqual([r for r, _ in self.calls], ["analyst", "developer", "reviewer", "static", "tester"])

    def test_three_iteration_limit_and_explicit_limitations(self):
        def runner(role, state):
            result = self.runner(role, state)
            if role == "tester":
                result["status"] = "needs_changes"
            return result
        graph = build_graph(runner, self.root, InMemorySaver())
        result = self.start(graph)
        self.assertEqual(result["iteration"], 3)
        self.assertEqual(sum(role == "tester" for role, _ in self.calls), 3)
        self.assertEqual(sum(role == "analyst" for role, _ in self.calls), 1)
        invalid = graph.invoke(Command(resume={"decision": "approve"}), self.config)
        self.assertIn("acknowledgment", invalid["__interrupt__"][0].value["error"])
        result = graph.invoke(Command(resume={"decision": "approve", "acknowledge_limitations": True}), self.config)
        self.assertEqual(result["status"], "approved_with_limitations")

    def test_human_changes_trigger_all_checks_again(self):
        graph = build_graph(self.runner, self.root, InMemorySaver())
        self.start(graph)
        result = graph.invoke(Command(resume={"decision": "request_changes", "feedback": "Add edge case"}), self.config)
        self.assertIn("__interrupt__", result)
        self.assertEqual(result["iteration"], 2)
        self.assertEqual(self.calls[-4:], [(r, 2) for r in ["developer", "reviewer", "static", "tester"]])

    def test_role_inputs_and_repair_feedback_are_passed_in_state(self):
        received = []

        def runner(role, state):
            received.append((role, state))
            return self.runner(role, state)

        graph = build_graph(runner, self.root, InMemorySaver())
        result = self.start(graph)
        self.assertEqual(received[1][1]["reports"]["analyst"]["report"], "Examined analyst")
        self.assertEqual(result["__interrupt__"][0].value["review_package"]["reports"], result["reports"])
        graph.invoke(Command(resume={"decision": "request_changes", "feedback": "Add coverage"}), self.config)
        repaired = next(state for role, state in received if role == "developer" and state["iteration"] == 2)
        self.assertEqual(repaired["human_feedback"], "Add coverage")
        self.assertIn("tester", repaired["reports"])
        self.assertEqual(len(repaired["history"]), 5)
        self.assertFalse(self.output.exists())

    def test_source_change_prevents_stale_approval(self):
        graph = build_graph(self.runner, self.root, InMemorySaver())
        self.start(graph)
        (self.root / "changed.py").write_text("x = 1", encoding="utf-8")
        invalid = graph.invoke(Command(resume={"decision": "approve"}), self.config)
        self.assertIn("Source changed", invalid["__interrupt__"][0].value["error"])

    def test_sqlite_resume_after_rebuilding_graph(self):
        database = str(self.root / ".ai-coder" / "checkpoints.sqlite")
        self.output.mkdir(parents=True)
        with SqliteSaver.from_conn_string(database) as saver:
            self.start(build_graph(self.runner, self.root, saver))
        with SqliteSaver.from_conn_string(database) as saver:
            graph = build_graph(None, self.root, saver)
            result = graph.invoke(Command(resume={"decision": "reject"}), self.config)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reports"]["analyst"]["report"], "Examined analyst")
        self.assertEqual(result["human_reviews"][0]["decision"], "reject")
        self.assertEqual(list(self.root.rglob("*.md")), [])


class RuntimeTests(unittest.TestCase):
    def test_write_permissions_and_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            readonly = Workspace(directory)
            with self.assertRaises(ValueError):
                readonly.execute("write_file", {"path": "a.py", "content": ""})
            writable = Workspace(directory, writable=True)
            for name in ["../escape.py", ".env", ".ai-coder/state.json"]:
                with self.assertRaises(ValueError):
                    writable.execute("write_file", {"path": name, "content": ""})
            writable.execute("write_file", {"path": "tests/a.py", "content": "x = 1"})
            self.assertEqual((Path(directory) / "tests/a.py").read_text(), "x = 1")

    def test_model_cannot_claim_unexecuted_checks_passed(self):
        class Backend:
            def respond(self, history, tools):
                return [{"type": "message", "content": [{"type": "output_text", "text":
                        json.dumps({"status": "pass", "report": "All good"})}]}]
        with tempfile.TemporaryDirectory() as directory:
            runner = ModelRunner(Backend(), directory, test_commands=[[sys.executable, "-m", "unittest"]])
            self.assertEqual(runner("tester", {})["status"], "blocked")

    def test_check_exit_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, commands=[[sys.executable, "-c", "raise SystemExit(7)"]])
            result = json.loads(workspace.execute("run_check", {"index": 0}))
            self.assertEqual(result["exit_code"], 7)
            with self.assertRaises(ValueError):
                workspace.execute("run_check", {"index": -1})


if __name__ == "__main__":
    unittest.main()
