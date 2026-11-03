"""The repository must extract identically on case-insensitive file systems (macOS, Windows): no two paths may differ
only by letter case, or one silently replaces the other."""
import os
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".git", "__pycache__", ".venv", "node_modules", "build", ".dart_tool", "artifacts"}


class CaseInsensitivePaths(unittest.TestCase):
    def test_no_paths_differ_only_by_case(self):
        seen = defaultdict(set)
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP and not (Path(base) == ROOT / "data" and d == "gold")]
            for name in dirs + files:
                rel = os.path.relpath(os.path.join(base, name), ROOT)
                seen[rel.lower()].add(rel)
        clashes = sorted(v for v in seen.values() if len(v) > 1)
        self.assertEqual(clashes, [], f"paths that collide on macOS/Windows: {clashes[:10]}")


if __name__ == "__main__":
    unittest.main()
