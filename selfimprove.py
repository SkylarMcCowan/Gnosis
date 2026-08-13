"""Self-improve scaffolding: propose and implement repository changes autonomously.

This module provides a minimal, opinionated controller that can:
- propose a feature plan (string description)
- write files to the workspace
- run unit tests via `python -m unittest`
- (optionally) produce a git diff/patch for review

Safety: this scaffold does NOT perform `git commit` or push by default. To enable
automatic commits, set the environment variable `SELFIMPROVE_ALLOW_COMMITS=1`.
"""
import os
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SelfImprove:
    def __init__(self, allow_commits: bool = False):
        self.allow_commits = allow_commits or os.getenv("SELFIMPROVE_ALLOW_COMMITS") == "1"

    def propose_and_create(self, files: dict, run_tests: bool = True) -> dict:
        """Create the given files (path -> content). Returns a report dict.

        files: mapping of relative-path -> file-content (str)
        """
        created = []
        for relpath, content in files.items():
            p = ROOT.joinpath(relpath)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as fh:
                fh.write(content)
            created.append(str(p.relative_to(ROOT)))

        report = {"created_files": created}

        if run_tests:
            test_result = self.run_tests()
            report["tests"] = test_result

        return report

    def run_tests(self) -> dict:
        """Run unit tests using the stdlib unittest discovery."""
        cmd = ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
            return {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            return {"error": str(e)}

    def git_diff(self) -> str:
        """Return a git diff of workspace changes (if git is available)."""
        try:
            proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT), capture_output=True, text=True)
            if proc.returncode != 0:
                return "git status failed: " + proc.stderr
            if not proc.stdout.strip():
                return "no changes"

            diff = subprocess.run(["git", "diff"], cwd=str(ROOT), capture_output=True, text=True)
            return diff.stdout
        except FileNotFoundError:
            return "git not available"


def example_autogen_feature():
    """Create a small utility function and tests as a demo of autonomous work."""
    si = SelfImprove()
    files = {
        "utils.py": """def reverse_string(s: str) -> str:\n    \"Return the reversed string.\"\n    return s[::-1]\n""",
        "tests/test_utils.py": """import unittest\nfrom utils import reverse_string\n\nclass TestUtils(unittest.TestCase):\n    def test_reverse(self):\n        self.assertEqual(reverse_string('abc'), 'cba')\n\nif __name__ == '__main__':\n    unittest.main()\n""",
    }
    return si.propose_and_create(files)


def load_todo_list() -> str:
    todo_path = ROOT.joinpath("TODO.md")
    if not todo_path.exists():
        return ""
    try:
        return todo_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def example_autogen_feature():
    """Create a small utility function and tests as a demo of autonomous work."""
    si = SelfImprove()
    files = {
        "utils.py": """def reverse_string(s: str) -> str:\n    \"Return the reversed string.\"\n    return s[::-1]\n""",
        "tests/test_utils.py": """import unittest\nfrom utils import reverse_string\n\nclass TestUtils(unittest.TestCase):\n    def test_reverse(self):\n        self.assertEqual(reverse_string('abc'), 'cba')\n\nif __name__ == '__main__':\n    unittest.main()\n""",
    }
    return si.propose_and_create(files)


if __name__ == "__main__":
    todo_list = load_todo_list()
    if todo_list:
        print("Loaded TODO.md for self-improve guidance.\n")
        print(todo_list)
    print(json.dumps(example_autogen_feature(), indent=2))
