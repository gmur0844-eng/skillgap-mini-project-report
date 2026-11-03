"""
Stage observability: wall time, peak Python heap (tracemalloc), process RSS
(psutil when present) and record counts per stage, plus the
pages -> courses -> units -> topics -> concepts -> mappings -> skills funnel.
"""
import time
import tracemalloc
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import psutil
except ImportError:  # optional -- RSS is reported as None without it
    psutil = None


class RunObserver:
    def __init__(self, listener=None):
        self.stages = []
        self.funnel = {}
        # listener(event, record): "start" before a stage runs, "end" after it (record carries status, duration and the
        # stage's own counts). Progress reporting only: a listener error is swallowed and never affects the run.
        self.listener = listener
        if not tracemalloc.is_tracing():
            tracemalloc.start()

    @contextmanager
    def stage(self, name, **attrs):
        tracemalloc.reset_peak()
        started = time.perf_counter()
        record = {"stage": name, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **attrs}
        self._notify("start", record)
        try:
            yield record
            record.setdefault("status", "OK")
        except Exception as exc:
            record["status"] = "ERROR"
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _, peak = tracemalloc.get_traced_memory()
            record["duration_s"] = round(time.perf_counter() - started, 3)
            record["peak_python_heap_mb"] = round(peak / 1_048_576, 2)
            record["rss_mb"] = round(psutil.Process().memory_info().rss / 1_048_576, 1) if psutil else None
            self.stages.append(record)
            self._notify("end", record)

    def _notify(self, event, record):
        if self.listener is None:
            return
        try:
            self.listener(event, dict(record))
        except Exception:  # noqa: BLE001 -- progress is advisory; the pipeline's result never depends on it
            pass

    def count(self, key, value):
        self.funnel[key] = value

    def report(self):
        return {"stages": self.stages, "funnel": self.funnel,
                "total_duration_s": round(sum(s.get("duration_s", 0) for s in self.stages), 3)}
