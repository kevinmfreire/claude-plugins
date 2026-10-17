#!/usr/bin/env python3
"""Local fantasy draft board (standard library only).

Yahoo's API needs OAuth and cannot make picks, so the board is kept locally:
import rankings, record each pick as it happens, and ask what is left.
State lives in ~/.cache/yahoo-fantasy-skill/draft.json.
"""
import argparse
import csv
import difflib
import json
import os
import sys

STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "yahoo-fantasy-skill")
STATE = os.path.join(STATE_DIR, "draft.json")


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def load():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        die("no draft board yet. Run `init` first.")


def save(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


def team_on_clock(s, n):
    """Draft slot (1-based) for overall pick n (1-based)."""
    t = s["teams"]
    rnd, idx = divmod(n - 1, t)
    if s["type"] == "snake" and rnd % 2 == 1:
        return t - idx
    return idx + 1


def my_picks_left(s):
    done = len(s["picks"])
    total = s["teams"] * s["rounds"]
    return [n for n in range(done + 1, total + 1) if team_on_clock(s, n) == s["me"]]


def find(s, name):
    names = [p["name"] for p in s["players"]]
    low = {n.lower(): n for n in names}
    if name.lower() in low:
        return low[name.lower()]
    subs = [n for n in names if name.lower() in n.lower()]
    if len(subs) == 1:
        return subs[0]
    close = subs or difflib.get_close_matches(name, names, n=5, cutoff=0.6)
    die("no unique match for %r.%s" % (name, " Did you mean: " + ", ".join(close[:5]) if close else ""))


def drafted(s):
    return {p["player"] for p in s["picks"]}


def cmd_init(a):
    s = {"teams": a.teams, "rounds": a.rounds, "me": a.slot, "type": a.type,
         "format": a.format, "players": [], "picks": []}
    save(s)
    print("Board ready: %d teams, %d rounds, %s, you pick from slot %d (%s)."
          % (a.teams, a.rounds, a.type, a.slot, a.format))


def cmd_rankings(a):
    s = load()
    players = []
    with open(a.file, "r", encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            players.append({"rank": int(row.get("rank") or i), "name": row["name"],
                            "pos": row.get("pos", ""), "team": row.get("team", ""),
                            "note": row.get("note", "")})
    players.sort(key=lambda p: p["rank"])
    s["players"] = players
    save(s)
    print("Loaded %d ranked players." % len(players))


def cmd_pick(a):
    s = load()
    name = find(s, " ".join(a.player))
    if name in drafted(s):
        die("%s is already drafted." % name)
    n = len(s["picks"]) + 1
    if n > s["teams"] * s["rounds"]:
        die("draft is complete.")
    slot = a.slot or team_on_clock(s, n)
    s["picks"].append({"n": n, "slot": slot, "player": name})
    save(s)
    print("#%d (slot %d): %s%s" % (n, slot, name, "  <- you" if slot == s["me"] else ""))
    cmd_status(a, s)


def cmd_undo(a):
    s = load()
    if not s["picks"]:
        die("no picks to undo.")
    p = s["picks"].pop()
    save(s)
    print("Removed pick #%d: %s" % (p["n"], p["player"]))


def cmd_status(a, s=None):
    s = s or load()
    n = len(s["picks"]) + 1
    if n > s["teams"] * s["rounds"]:
        print("Draft complete.")
        return
    on = team_on_clock(s, n)
    rnd = (n - 1) // s["teams"] + 1
    mine = my_picks_left(s)
    nxt = mine[0] if mine else None
    print("On the clock: pick #%d (round %d), slot %d%s." % (n, rnd, on, " (YOU)" if on == s["me"] else ""))
    if nxt and nxt != n:
        print("Your next pick: #%d, in %d picks." % (nxt, nxt - n))


def cmd_available(a):
    s = load()
    gone = drafted(s)
    pos = {p.strip().upper() for p in a.pos.split(",")} if a.pos else None
    shown = 0
    for p in s["players"]:
        if p["name"] in gone:
            continue
        if pos and not pos & {x.strip().upper() for x in p["pos"].replace("/", ",").split(",")}:
            continue
        print("%3d. %-24s %-8s %-4s %s" % (p["rank"], p["name"], p["pos"], p["team"], p["note"]))
        shown += 1
        if shown >= a.limit:
            break


def cmd_mine(a):
    s = load()
    rows = [p for p in s["picks"] if p["slot"] == s["me"]]
    meta = {p["name"]: p for p in s["players"]}
    for p in rows:
        m = meta.get(p["player"], {})
        print("#%-3d %-24s %-8s %s" % (p["n"], p["player"], m.get("pos", ""), m.get("team", "")))
    if not rows:
        print("No picks yet.")


def cmd_board(a):
    s = load()
    for p in s["picks"][-a.last:]:
        print("#%-3d slot %-2d %s%s" % (p["n"], p["slot"], p["player"], "  <- you" if p["slot"] == s["me"] else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--teams", type=int, required=True)
    p.add_argument("--rounds", type=int, required=True)
    p.add_argument("--slot", type=int, required=True, help="your draft position")
    p.add_argument("--type", choices=["snake", "linear"], default="snake")
    p.add_argument("--format", default="9cat", help="9cat, 8cat or points")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("rankings")
    p.add_argument("file", help="CSV with columns rank,name,pos,team,note")
    p.set_defaults(fn=cmd_rankings)
    p = sub.add_parser("pick")
    p.add_argument("player", nargs="+")
    p.add_argument("--slot", type=int, help="override the slot that made this pick")
    p.set_defaults(fn=cmd_pick)
    sub.add_parser("undo").set_defaults(fn=cmd_undo)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("available")
    p.add_argument("--pos")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(fn=cmd_available)
    sub.add_parser("mine").set_defaults(fn=cmd_mine)
    p = sub.add_parser("board")
    p.add_argument("--last", type=int, default=12)
    p.set_defaults(fn=cmd_board)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
