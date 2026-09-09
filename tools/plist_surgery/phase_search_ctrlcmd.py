#!/usr/bin/env python3
"""phase_search_ctrlcmd - ⌃⌘ on the main search rows (2026-09-09).

Vex ruling 2026-09-08 (final): search rows carry ⌃⇧ Open as sticky note
and ⌃⌘ Start focus. The python side (everything_search.py) already stamps
both chords; the canvas had no ⌃⌘ edge on the Everything script filter, so
the chord fell dead. This adds ONE modifier edge and nothing else:

  Everything SF E86FBD12  --⌃⌘ (1310720)-->  junction 56151466
  (the same junction plain ⏎ and ⌃⇧ already feed: Call-ET modOpen →
   ET modOpen → the runscript whose bash case routes xact:* to xact.py,
   so the row's ctrl+cmd arg 'xact:focus_open:<pid>:<tid>' executes).

Prediction: objects 393→393, edges 350→351, ETs unchanged, unused ETs 1→1
(GridPeek, osascript-fired - never clean it).

Usage: python3 phase_search_ctrlcmd.py <path-to-info.plist>   (scratch first, then live)
"""
import os
import plistlib
import sys

SF = "E86FBD12-4202-4205-A6B9-E63851E8A01A"
JUNCTION = "56151466-748D-4737-985E-DD05C212B5BF"
CTRL_SHIFT = 393216
CTRL_CMD = 1310720


def main(path):
    with open(path, "rb") as f:
        pl = plistlib.load(f)
    objs = {o["uid"]: o for o in pl["objects"]}
    assert len(pl["objects"]) == 393, f"object count {len(pl['objects'])} != 393"
    edges_before = sum(len(v) for v in pl["connections"].values())
    assert edges_before == 350, f"edge count {edges_before} != 350"
    sf = objs.get(SF)
    assert sf and sf["type"] == "alfred.workflow.input.scriptfilter", "Everything SF missing"
    assert "everything_search.py" in sf["config"].get("script", ""), "SF is not the search filter"
    assert objs.get(JUNCTION, {}).get("type") == "alfred.workflow.utility.junction", "junction missing"
    conns = pl["connections"][SF]
    template = next((c for c in conns if c.get("modifiers") == CTRL_SHIFT
                     and c["destinationuid"] == JUNCTION), None)
    assert template, "⌃⇧ edge to the ⏎ junction missing - canvas drifted"
    assert not any(c.get("modifiers") == CTRL_CMD for c in conns), "⌃⌘ edge already present"

    # ── mutation: clone the ⌃⇧ edge with the ⌃⌘ modifier mask ────────────
    edge = dict(template)
    edge["modifiers"] = CTRL_CMD
    conns.append(edge)

    # ── invariants ────────────────────────────────────────────────────────
    for src, lst in pl["connections"].items():
        assert src in objs, f"edge source {src} not an object"
        for c in lst:
            assert c["destinationuid"] in objs, f"dangling edge {src} → {c['destinationuid']}"
    ets = {o["config"].get("triggerid") for o in pl["objects"]
           if o["type"] == "alfred.workflow.trigger.external"}
    for o in pl["objects"]:
        if o["type"] == "alfred.workflow.output.callexternaltrigger":
            assert o["config"].get("externaltriggerid") in ets, f"Call-ET {o['uid']} → missing ET"
    edges_after = sum(len(v) for v in pl["connections"].values())
    assert len(pl["objects"]) == 393 and edges_after == 351, "delta mismatch"

    # ── atomic write in the target's own directory ────────────────────────
    tmp = os.path.join(os.path.dirname(os.path.abspath(path)), ".info.plist.phase_search_ctrlcmd.tmp")
    with open(tmp, "wb") as f:
        plistlib.dump(pl, f, sort_keys=False)
    os.replace(tmp, path)
    print(f"phase_search_ctrlcmd: objects 393→393, edges {edges_before}→{edges_after}, "
          f"+1 edge {SF[:8]} ⌃⌘ → {JUNCTION[:8]}")


if __name__ == "__main__":
    main(sys.argv[1])
