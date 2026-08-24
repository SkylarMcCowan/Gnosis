"""Regression tests for /job and /persona agent switching (webagent.py:2536-2560)."""
import webagent


def test_switch_agent_to_known_persona(isolated_data_dir):
    result = webagent.switch_agent("ethics")
    assert webagent.context.current_agent == "ethics"
    assert "Ethics Advisor" in result or "ethics" in result.lower()


def test_switch_agent_to_default_clears_persona(isolated_data_dir):
    webagent.switch_agent("ethics")
    result = webagent.switch_agent("default")
    assert webagent.context.current_agent is None
    assert "default" in result.lower()


def test_switch_agent_rejects_unknown_name(isolated_data_dir):
    result = webagent.switch_agent("not_a_real_agent")
    assert webagent.context.current_agent is None
    assert "Unknown agent" in result


def test_job_command_with_no_args_lists_agents():
    result = webagent.job_command(None)
    for key in webagent.AVAILABLE_AGENTS:
        assert key in result


def test_job_command_single_agent_delegates_to_switch_agent(isolated_data_dir):
    result = webagent.job_command("philosophy")
    assert webagent.context.current_agent == "philosophy"
    assert "Philosophy Bridge" in result


def test_job_command_multi_agent_collaboration(isolated_data_dir):
    result = webagent.job_command("research,ethics")
    assert isinstance(result, str)
    assert "research" in result.lower() and "ethics" in result.lower()
