"""NAKS demo.

    python3 examples/demo.py    # queues 2 requests; say /naks in a Claude chat, then run it again
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
from naks_client import get, pending, submit  # noqa: E402

NOTE = "Ship the onboarding redesign by Friday. Ask Sam for the new illustrations and book a usability test."

# submit() queues both requests first, so a single /naks answers them together.
ids = {
    "title": submit("Write a title of at most 5 words for this note.", inputs={"note": NOTE}, task="demo-title"),
    "tags": submit(
        "Extract 2-4 short tags from this note.",
        inputs={"note": NOTE},
        schema={"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        task="demo-tags",
    ),
}

waiting = [rid for rid in ids.values() if rid in pending()]
if waiting:
    print(f"{len(waiting)} request(s) queued in .naks/requests/. Run /naks in a Claude chat, then run this script again.")
else:
    for name, rid in ids.items():
        print(f"{name}: {get(rid)}")
