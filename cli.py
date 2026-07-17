#!/usr/bin/env python3
"""Drive the venture flow from the terminal -- the approval loop as a REPL.

    python3 cli.py                        # interactive session
    python3 cli.py "start cozy desk art"  # one command, then exit
    STOREFRONT_URL=http://host:8820 python3 cli.py

Talks to the generation service's /api/agents/shop/run and pretty-prints the
stage events. Same commands as anywhere else: start <seed>, pick <n>,
approve [notes], revise <notes>, status, show <stage>.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("STOREFRONT_URL", "http://localhost:8820")


def run(command: str) -> None:
    body = json.dumps({"input": command}).encode()
    req = urllib.request.Request(f"{BASE}/api/agents/shop/run", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)
    for ev in out.get("events", []):
        if ev["type"] == "tool_call":
            print(f"  .. {ev['tool']} {json.dumps(ev.get('args', {}))[:80]}")
    if out.get("error"):
        print(f"!! {out['error']}")
        return
    o = out.get("output") or {}
    for line in json.dumps({k: v for k, v in o.items()
                            if k not in ("message", "ladder")},
                           indent=2).splitlines()[:40]:
        print(f"   {line}")
    if o.get("ladder"):
        print("   " + " -> ".join(f"{s['stage']}:{s['status']}" for s in o["ladder"]))
    print(f"\n{o.get('message', '')}")


def main() -> None:
    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]))
        return
    print(f"storefront-ai flow @ {BASE} -- 'status' to see where you are, "
          "ctrl-d to quit")
    while True:
        try:
            cmd = input("shop> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if cmd:
            run(cmd)


if __name__ == "__main__":
    main()
