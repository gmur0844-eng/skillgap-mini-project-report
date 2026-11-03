"""
Quarantine: malformed or noise records are set aside WITH the reason and the
stage that rejected them. Nothing is deleted; the raw source evidence stays
in BRONZE, and the quarantined record itself is written to GOLD's
quarantine.jsonl so every exclusion can be audited.
"""
from collections import Counter


class Quarantine:
    def __init__(self):
        self.items = []

    def add(self, stage, record, reason):
        self.items.append({"stage": stage, "reason": reason, "record": record})

    def count(self, stage=None):
        return sum(1 for item in self.items if stage is None or item["stage"] == stage)

    def summary(self):
        by_stage = Counter(item["stage"] for item in self.items)
        by_reason = Counter(item["reason"].split(":")[0].split("(")[0] for item in self.items)
        return {"total": len(self.items), "by_stage": dict(sorted(by_stage.items())),
                "by_reason": dict(sorted(by_reason.items()))}
