"""Bounded model/tool execution and auditable, workspace-scoped file access."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from .contracts import CONTRACT

EXCLUDED = {".git", ".venv", "venv", "__pycache__", "node_modules", "outputs", ".ai-coder"}


def source_files(root: Path):
    """Skip generated state and secret files; never follow directory symlinks."""
    import os
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith("."))
        for name in sorted(files):
            path = Path(directory) / name
            if not name.startswith(".") and not path.is_symlink():
                yield path


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def schema(name, description, properties):
    return {"type": "function", "name": name, "description": description,
            "strict": True, "parameters": {"type": "object",
            "properties": properties, "required": list(properties),
            "additionalProperties": False}}


class Workspace:
    def __init__(self, root, writable=False, commands=()):
        self.root = Path(root).resolve(strict=True)
        self.writable = writable
        self.commands = commands
        self.evidence = {}

    def path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Path escapes repository")
        parts = path.relative_to(self.root).parts
        if any(p in EXCLUDED or p.startswith(".") for p in parts):
            raise ValueError("Hidden or generated paths are unavailable")
        return path

    def schemas(self):
        string = {"type": "string"}
        result = [schema("list_files", "List repository file paths", {}),
                  schema("read_file", "Read UTF-8 repository file, up to 60000 bytes", {"path": string})]
        if self.writable:
            result.append(schema("write_file", "Write complete UTF-8 source or test file",
                                 {"path": string, "content": string}))
        if self.commands:
            result.append(schema("run_check", "Run a preconfigured check by zero-based index",
                                 {"index": {"type": "integer"}}))
        return result

    def execute(self, name, args):
        if name == "list_files" and not args:
            return "\n".join(p.relative_to(self.root).as_posix()
                             for p in source_files(self.root))[:60000]
        if name == "read_file" and set(args) == {"path"}:
            with self.path(args["path"]).open("rb") as handle:
                data = handle.read(60001)
            if len(data) > 60000:
                raise ValueError("File exceeds 60000 bytes")
            return data.decode("utf-8-sig")
        if name == "write_file" and self.writable and set(args) == {"path", "content"}:
            path = self.path(args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"Wrote {args['path']}"
        if name == "run_check" and set(args) == {"index"}:
            index = args["index"]
            if type(index) is not int or not 0 <= index < len(self.commands):
                raise ValueError("Invalid check index")
            argv = self.commands[index]
            try:
                completed = subprocess.run(argv, cwd=self.root, capture_output=True,
                                           text=True, timeout=120, shell=False,
                                           encoding="utf-8", errors="replace")
                record = {"argv": argv, "cwd": str(self.root), "exit_code": completed.returncode,
                          "output": (completed.stdout + completed.stderr)[-40000:]}
            except (OSError, subprocess.TimeoutExpired) as error:
                record = {"argv": argv, "cwd": str(self.root), "exit_code": None,
                          "output": str(error), "blocked": True}
            self.evidence[str(index)] = record
            return json.dumps(record)
        raise ValueError("Tool or arguments not permitted for this role")


class ModelRunner:
    """One fresh model conversation per role and iteration; no shared chat history."""
    def __init__(self, backend, root, static_commands=(), test_commands=(), max_steps=24):
        self.backend, self.root = backend, Path(root)
        self.commands = {"static": static_commands, "tester": test_commands}
        self.max_steps = max_steps

    def __call__(self, role, state):
        from .roles import ROLES

        spec = ROLES[role]
        commands = self.commands.get(role, ())
        workspace = Workspace(self.root, writable=role == "developer", commands=commands)
        context = {key: state.get(key) for key in ("task", "reports", "human_feedback", "iteration")}
        history = [{"role": "developer", "content": spec.instructions + CONTRACT},
                   {"role": "user", "content": json.dumps({"context": context, "checks": commands})}]
        try:
            for _ in range(self.max_steps):
                output = self.backend.respond(history, workspace.schemas())
                history.extend(output)
                calls = [item for item in output if item.get("type") == "function_call"]
                if len(calls) > 20:
                    raise ValueError("Too many tool calls")
                if not calls:
                    text = "\n".join(p["text"] for item in output
                                     for p in item.get("content", []) if p.get("type") == "output_text")
                    result = json.loads(text)
                    if not isinstance(result, dict):
                        raise ValueError("Role response must be a JSON object")
                    if result.get("status") not in {"pass", "needs_changes", "blocked"}:
                        raise ValueError("Invalid role status")
                    if not isinstance(result.get("report"), str) or not result["report"].strip():
                        raise ValueError("Missing role report")
                    break
                for call in calls:
                    try:
                        value = workspace.execute(call["name"], json.loads(call["arguments"]))
                    except (ValueError, TypeError, OSError) as error:
                        value = json.dumps({"error": str(error)})
                    history.append({"type": "function_call_output", "call_id": call["call_id"], "output": value})
            else:
                raise ValueError("Role step limit exceeded")
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            result = {"status": "blocked", "report": f"Role execution blocked: {error}"}
        if role in self.commands:
            evidence = workspace.evidence
            if not commands or len(evidence) != len(commands) or any(
                    r.get("blocked") for r in evidence.values()):
                result["status"] = "blocked"
            elif any(r["exit_code"] != 0 for r in evidence.values()):
                result["status"] = "needs_changes"
            if role == "tester" and any(re.search(
                    r"Ran 0 tests|no tests ran|collected 0 items", r["output"], re.I)
                    for r in evidence.values()):
                result["status"] = "blocked"
            result["report"] += "\n\n## Executed checks\n```json\n" + json.dumps(evidence, indent=2) + "\n```"
        return result
