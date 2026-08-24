"""The generic "read one turn, dispatch it, fall back if nothing matched"
loop shape behind webagent.py's main(). Like command_router.py, this has no
idea what a prompt even means - webagent.py supplies every hook (how to read
one, what runs first, the router, what happens when nothing matches) and
this module just sequences them the same way every turn.
"""


class Orchestrator:
    def __init__(self, read_input, before_dispatch, router, on_unmatched):
        self.read_input = read_input
        self.before_dispatch = before_dispatch
        self.router = router
        self.on_unmatched = on_unmatched

    def run_once(self):
        """Process exactly one turn. Returns True if a prompt was actually
        processed (dispatched or handled by the fallback), False if
        read_input yielded nothing to process (e.g. voice recognition heard
        nothing this cycle) - the caller should just loop again either way."""
        prompt = self.read_input()
        if prompt is None:
            return False
        self.before_dispatch(prompt)
        if not self.router.dispatch(prompt):
            self.on_unmatched(prompt)
        return True

    def run_forever(self):
        while True:
            self.run_once()
