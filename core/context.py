"""Session/conversation state: the "where are we right now" that used to
live as nine separate module-level globals in webagent.py, each mutated via
its own `global` declaration in whichever function happened to touch it.

A single shared Context *instance* (not the class) is the point: every
reader/writer - webagent.py itself, tarot.py, webagent_gui.py - reaches the
same object and reads/writes its attributes fresh on every access. That's
what makes it safe to hand to other modules, unlike the old pattern of
`from webagent import assistant_convo`, which captured whatever list object
existed *at import time* and kept using it even after webagent.py later
rebound its own module-level `assistant_convo` name to a new list (see
tarot.py's now-fixed stale binding, logged in TODO.md Phase 1).
"""


class Context:
    def __init__(self):
        self.assistant_convo = []
        self.current_agent = None       # Current specialized agent persona
        self.voice_mode = False         # live speech input mode
        self.tts_mode = False           # if on, responses are read aloud (in text mode)
        self.web_search_mode = True     # model decides per-turn whether to actually search; on by default
        self.reasoning_mode = False
        self.deep_think_mode = False    # evidence-led, structured research synthesis
        self.unfiltered_mode = False    # Toggle for unfiltered model mode
        self.coding_mode = False        # Toggle for coding model mode
        self.selected_model = None      # explicit local-model override (Ollama tag); None means fall back to mode-based selection
        self.status_callback = None     # optional callable(str), set for the duration of one chat_response() call so a UI (the GUI's status label) can show what's happening; None means nothing is listening


context = Context()
