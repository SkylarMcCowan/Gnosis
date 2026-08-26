"""Minimal publish/subscribe event bus.

Phase 12 is where this starts actually being used: real call sites publish
one of the named events below instead of calling several downstream
functions directly, and real subscribers (registered once, at webagent.py
import time) react. See core/activity_log.py for the one subscriber every
event gets (a flat activity log) and webagent.py's `_register_event_subscribers()`
for the rest.

Named events, from the roadmap's own list - wired for real:
    SEARCH_COMPLETED  - a web search returned results (search_web)
    TASK_COMPLETED    - a persona-driven chat turn finished (chat_response/
                        _handle_unmatched_prompt) - the one real multi-
                        subscriber case: replaces the direct
                        save_agent_memory + save_conversation_insights
                        calls that used to be duplicated at both call sites
    SKILL_CREATED     - builder/pipeline.py generated and validated a new
                        skill (regardless of pass/fail - "created" means
                        written, not registered; nothing here ever
                        registers anything automatically)
    KNOWLEDGE_UPDATED - record_to_knowledge_base wrote a file
    MEMORY_CREATED    - save_agent_memory wrote a file
    TEST_PASSED / TEST_FAILED - a real test run's outcome, from either
                        self-improve's _run_self_improve_tests or Phase 9's
                        validate_generated_skill
    TOOL_SELECTION_MADE - the model was asked whether/which tool(s) would
                        help a turn (_select_tool_action, _select_tool_actions)
                        and decided - including an empty decision ("no tool
                        applies"/"I don't know"). Logged deliberately even
                        on that empty case: the point isn't just recording
                        successful tool use, it's a timestamped trail of
                        every selection decision (what was asked, what was
                        picked, why) to review later instead of guessing
                        from a live trace why a turn didn't use a tool it
                        maybe should have.
    TOOL_EXECUTION_COMPLETED - a selected tool actually ran, success or
                        failure (_execute_tool_action, _execute_research_tool_action).
                        A selection decision alone doesn't say whether the
                        call worked - this is what closes that gap for
                        after-the-fact review: which tool, what arguments,
                        whether it succeeded, and the failure reason if not.
    APP_STARTED       - webagent.py finished importing and registering its
                        tools/skills/event subscribers - one row per process
                        launch, so "was the app even running, and since
                        when" is answerable from the log instead of assumed
                        from context.

Not wired, for stated reasons rather than left silently missing:
    TOOL_CREATED  - nothing generates raw Tool subclasses (Phase 9 only
                    generates Skills, which compose already-registered
                    Tools) - there's no real call site for this yet.
    TASK_FAILED   - self-improve's and Phase 9's failure outcomes already
                    have a richer real signal (Phase 5's Experience log,
                    which a bare event can't match - goal, plan, tools
                    used, lessons); a conversational task genuinely
                    "failing" (not just completing) doesn't have a clear
                    real trigger in the codebase yet. Forcing a fit here
                    would be ceremony, not a real signal.
"""
from collections import defaultdict

SEARCH_COMPLETED = "SEARCH_COMPLETED"
TASK_COMPLETED = "TASK_COMPLETED"
SKILL_CREATED = "SKILL_CREATED"
KNOWLEDGE_UPDATED = "KNOWLEDGE_UPDATED"
MEMORY_CREATED = "MEMORY_CREATED"
TEST_PASSED = "TEST_PASSED"
TEST_FAILED = "TEST_FAILED"
TOOL_SELECTION_MADE = "TOOL_SELECTION_MADE"
TOOL_EXECUTION_COMPLETED = "TOOL_EXECUTION_COMPLETED"
APP_STARTED = "APP_STARTED"


class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_name, handler):
        self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name, handler):
        try:
            self._subscribers[event_name].remove(handler)
        except ValueError:
            pass

    def publish(self, event_name, **payload):
        """Call every handler subscribed to event_name with payload as
        keyword arguments. Iterates over a snapshot of the subscriber list,
        so a handler that subscribes/unsubscribes during publish doesn't
        change what this call itself notifies."""
        for handler in list(self._subscribers.get(event_name, ())):
            handler(**payload)


events = EventBus()
