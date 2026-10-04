"""Stand-in for PyGObject (GStreamer bindings) so tests run on machines without GStreamer.
Only used when the real `gi` cannot be imported; the robot always has the real one."""
def require_version(*a, **k): pass
class _R:
    def __getattr__(self, n): return _R()
    def __call__(self, *a, **k): return _R()
import sys, types
repository = types.ModuleType("gi.repository")
repository.__getattr__ = lambda n: _R()
sys.modules["gi.repository"] = repository
