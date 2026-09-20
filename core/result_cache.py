"""Small bounded cache for source data; never cache failures or generated answers."""
from collections import OrderedDict
import copy
import threading
import time


class ResultCache:
    def __init__(self, max_entries=128, clock=time.monotonic):
        self.max_entries = max_entries
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            expires, value = entry
            if self.clock() >= expires:
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
            return copy.deepcopy(value)

    def put(self, key, value, ttl):
        if not value:
            return
        with self.lock:
            self.entries[key] = (self.clock() + ttl, copy.deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)


subscription_cache = ResultCache()
