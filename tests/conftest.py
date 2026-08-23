import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRA = [ROOT, os.path.join(ROOT, "mcp-server"), os.path.join(ROOT, "sync")]

for p in EXTRA:
    if p not in sys.path:
        sys.path.insert(0, p)

existing = os.environ.get("PYTHONPATH", "")
merged = os.pathsep.join(EXTRA + ([existing] if existing else []))
os.environ["PYTHONPATH"] = merged
