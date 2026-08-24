"""SANDBOX + RUN TESTS: actually run a generated skill's generated tests,
inside an isolated sandbox Workspace (Phase 10), with a real, code-level
safety net that blocks any real tool_registry.execute call during the
run - regardless of whether the generated test correctly faked it as
instructed. Compile-checks both files before ever executing anything.

This is the one place in the whole pipeline where model-written code
actually runs. See builder/__init__.py's safety stance for what this does
and does not protect against.
"""
import os
import sys
import py_compile

from core.events import events, TEST_PASSED, TEST_FAILED
from sandbox.workspace import Workspace

_CONFTEST_CONTENT = '''
import pytest


@pytest.fixture(autouse=True)
def _block_real_tool_execution(monkeypatch):
    """Generated-code safety net: no test collected here may execute a
    real tool, no matter what the generated test does or forgets to mock
    - see builder/validator.py."""
    from tools.registry import registry as tool_registry

    def _refuse(name, **kwargs):
        raise RuntimeError(
            f"Blocked a real tool_registry.execute({name!r}) call during generated-code "
            "validation - generated tests must fake tool_registry.execute, never call it for real."
        )

    monkeypatch.setattr(tool_registry, "execute", _refuse)
'''


def validate_generated_skill(repo_root, skill_code, test_rel_path, test_code):
    """Returns (passed: bool, output: str). Never raises for an ordinary
    generation/compile/test failure - those are reported as passed=False
    with the failure text as output. Only a genuine infrastructure problem
    (e.g. Workspace itself failing to create) propagates, since that's not
    a "the generated code was bad" outcome the caller should silently
    treat the same way."""
    with Workspace(repo_root) as workspace:
        skill_path = os.path.join(workspace.path, "generated_skill.py")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_code)
        try:
            py_compile.compile(skill_path, doraise=True)
        except Exception as e:
            events.publish(TEST_FAILED, reason="generated skill does not compile")
            return False, f"generated skill code does not compile: {e}"

        test_abs_path = os.path.join(workspace.path, test_rel_path)
        os.makedirs(os.path.dirname(test_abs_path), exist_ok=True)
        # The generated test imports the skill as a sibling module, per
        # test_generator.py's prompt - drop a copy next to the test file
        # too, regardless of where in the workspace the test itself lives.
        sibling_skill_path = os.path.join(os.path.dirname(test_abs_path), "generated_skill.py")
        with open(sibling_skill_path, "w", encoding="utf-8") as f:
            f.write(skill_code)
        with open(test_abs_path, "w", encoding="utf-8") as f:
            f.write(test_code)
        try:
            py_compile.compile(test_abs_path, doraise=True)
        except Exception as e:
            events.publish(TEST_FAILED, reason="generated test does not compile")
            return False, f"generated test code does not compile: {e}"

        conftest_path = os.path.join(os.path.dirname(test_abs_path), "conftest.py")
        with open(conftest_path, "w", encoding="utf-8") as f:
            f.write(_CONFTEST_CONTENT)

        code, out, err = workspace.run(sys.executable, "-m", "pytest", "-q", test_rel_path)
        passed = code == 0
        events.publish(TEST_PASSED if passed else TEST_FAILED, reason="sandboxed generated-skill test run")
        return passed, (out + "\n" + err).strip()
