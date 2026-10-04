#!/usr/bin/env python3
"""Sleeper fantasy football CLI (read-only, standard library only).

Handles API calls, caching, and player-ID -> name joins so callers never
need to read raw API JSON. League ID comes from --league or the
SLEEPER_LEAGUE_ID environment variable.
"""
import argparse
import difflib
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.sleeper.app/v1"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "sleeper-skill")
PLAYERS_CACHE = os.path.join(CACHE_DIR, "players.json")
PLAYERS_TTL = 24 * 60 * 60
TIMEOUT = 30

FLEX_MAP = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "IDP_FLEX": {"DL", "LB", "DB"},
}
NON_POSITIONS = {"BN", "IR", "TAXI"}


class SleeperError(Exception):
    pass


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- API layer

def http_get(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": "sleeper-fantasy-skill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SleeperError("Not found (404): %s" % path)
        if e.code == 429:
            raise SleeperError("Rate limited by Sleeper (429). Wait a minute and retry.")
        raise SleeperError("Sleeper API returned HTTP %d for %s" % (e.code, path))
    except urllib.error.URLError as e:
        raise SleeperError(
            "Network error reaching api.sleeper.app (%s). The skill needs network access; "
            "sandboxed environments may block it." % e.reason
        )
    except (TimeoutError, OSError) as e:
        raise SleeperError("Network error reaching api.sleeper.app: %s" % e)
    except ValueError:
        raise SleeperError("Sleeper returned a non-JSON response for %s" % path)


def load_players(refresh=False):
    """All NFL players, cached for 24h as Sleeper requests."""
    if not refresh:
        try:
            if time.time() - os.path.getmtime(PLAYERS_CACHE) < PLAYERS_TTL:
                with open(PLAYERS_CACHE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
    data = http_get("/players/nfl")
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = PLAYERS_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, PLAYERS_CACHE)
    except OSError:
        pass
    return data


class League:
    """Loads league, users and rosters once and offers name lookups."""

    def __init__(self, league_id, user_id=None):
        self.id = league_id
        try:
            info = http_get("/league/%s" % league_id)
        except SleeperError as e:
            if "404" in str(e):
                info = None
            else:
                raise
        if not info:
            raise SleeperError("League %s not found. Check the league ID." % league_id)
        self.info = info
        self.users = http_get("/league/%s/users" % league_id) or []
        self.rosters = http_get("/league/%s/rosters" % league_id) or []
        user_by_id = {u["user_id"]: u for u in self.users}
        self.team_names = {}   # roster_id -> team name
        self.owner_names = {}  # roster_id -> display_name
        for r in self.rosters:
            u = user_by_id.get(r.get("owner_id"), {})
            owner = (u.get("display_name") or "Unknown").strip()
            team = ((u.get("metadata") or {}).get("team_name") or "").strip() or owner
            self.team_names[r["roster_id"]] = team
            self.owner_names[r["roster_id"]] = owner
        self.me = None  # roster_id owned by the configured Sleeper user
        for r in self.rosters:
            if user_id and (r.get("owner_id") == user_id or user_id in (r.get("co_owners") or [])):
                self.me = r["roster_id"]
        self.owner_of = {}  # player_id -> roster_id
        for r in self.rosters:
            for pid in (r.get("players") or []) + (r.get("reserve") or []) + (r.get("taxi") or []):
                self.owner_of[pid] = r["roster_id"]

    def team(self, roster_id):
        return self.team_names.get(roster_id, "Roster %s" % roster_id)

    def label(self, roster_id):
        return self.team(roster_id) + (" (you)" if roster_id == self.me else "")

    def scoring_type(self):
        rec = (self.info.get("scoring_settings") or {}).get("rec", 0)
        if rec >= 1:
            return "PPR"
        if rec >= 0.5:
            return "Half PPR"
        if rec == 0:
            return "Standard"
        return "Custom (%s per rec)" % rec

    def positions(self):
        """Set of player positions this league can actually start."""
        pos = set()
        for slot in self.info.get("roster_positions") or []:
            if slot in NON_POSITIONS:
                continue
            pos |= FLEX_MAP.get(slot, {slot})
        return pos


# ------------------------------------------------------------------ helpers

def pname(p, pid=None):
    if not p:
        return "Unknown(%s)" % pid
    n = p.get("full_name") or ("%s %s" % (p.get("first_name") or "", p.get("last_name") or "")).strip()
    return n or "Unknown(%s)" % pid


def pdesc(p, pid=None, injury=True):
    """Compact 'Name POS TEAM [INJ]' descriptor."""
    if not p:
        return "Unknown(%s)" % pid
    s = "%s %s %s" % (pname(p, pid), p.get("position") or "?", p.get("team") or "FA")
    if injury and p.get("injury_status"):
        s += " [%s]" % p["injury_status"]
    return s


def get_user(username):
    try:
        u = http_get("/user/%s" % urllib.request.quote(username, safe=""))
    except SleeperError as e:
        if "404" not in str(e):
            raise
        u = None
    if not u:
        raise SleeperError("Sleeper user '%s' not found. Use your Sleeper username (not display name)." % username)
    return u


def user_leagues(user_id, season=None):
    season = season or http_get("/state/nfl").get("league_season") or http_get("/state/nfl")["season"]
    return http_get("/user/%s/leagues/nfl/%s" % (user_id, season)) or []


def require_league(args):
    """League from --league / env, else from the user's leagues. Also finds 'me'."""
    username = args.username or os.environ.get("SLEEPER_USERNAME")
    lid = args.league or os.environ.get("SLEEPER_LEAGUE_ID")
    user_id = None
    if username:
        user = get_user(username)
        user_id = user["user_id"]
        if not lid:
            leagues = user_leagues(user_id)
            if not leagues:
                raise SleeperError("No NFL leagues found for '%s' this season. Pass --league ID." % username)
            if len(leagues) > 1:
                lines = ["  %s  %s" % (l["league_id"], (l.get("name") or "").strip()) for l in leagues]
                raise SleeperError("'%s' is in %d leagues; pick one with --league ID:\n%s"
                                   % (username, len(leagues), "\n".join(lines)))
            lid = leagues[0]["league_id"]
    if not lid:
        die("no league. Set SLEEPER_USERNAME (or pass --username) to auto-find your league, "
            "or pass --league ID / set SLEEPER_LEAGUE_ID.")
    return League(lid, user_id)


def current_week():
    st = http_get("/state/nfl")
    return st, int(st.get("week") or 1)


def emit(args, data, text_lines):
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print("\n".join(text_lines))


# ----------------------------------------------------------------- commands

def cmd_league(args):
    lg = require_league(args)
    st = http_get("/state/nfl")
    i = lg.info
    teams = []
    for r in sorted(lg.rosters, key=lambda r: (-(r.get("settings") or {}).get("wins", 0),
                                               -(r.get("settings") or {}).get("fpts", 0))):
        s = r.get("settings") or {}
        pts = s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100.0
        teams.append({
            "roster_id": r["roster_id"], "team": lg.team(r["roster_id"]),
            "owner": lg.owner_names[r["roster_id"]], "is_me": r["roster_id"] == lg.me,
            "wins": s.get("wins", 0), "losses": s.get("losses", 0), "ties": s.get("ties", 0),
            "points_for": round(pts, 2),
        })
    data = {
        "league_id": lg.id, "name": (i.get("name") or "").strip(), "season": i.get("season"),
        "status": i.get("status"), "current_nfl_week": st.get("week"),
        "season_type": st.get("season_type"), "scoring": lg.scoring_type(),
        "roster_positions": i.get("roster_positions"), "teams": teams,
    }
    if args.json:
        return emit(args, data, [])
    out = [
        "%s (%s season, %s)" % (data["name"], data["season"], data["status"]),
        "Scoring: %s | NFL week %s (%s)" % (data["scoring"], data["current_nfl_week"], data["season_type"]),
        "Roster slots: " + ", ".join(data["roster_positions"] or []),
        "Teams:",
    ]
    for t in teams:
        rec = "%d-%d" % (t["wins"], t["losses"]) + ("-%d" % t["ties"] if t["ties"] else "")
        out.append("  #%-2d %-28s %-6s %8.2f PF  (%s)%s" % (t["roster_id"], t["team"][:28], rec, t["points_for"], t["owner"],
                                                          "  <- you" if t["roster_id"] == lg.me else ""))
    emit(args, data, out)


def cmd_leagues(args):
    username = args.username or os.environ.get("SLEEPER_USERNAME")
    if not username:
        die("no username. Pass --username NAME or set SLEEPER_USERNAME.")
    user = get_user(username)
    leagues = user_leagues(user["user_id"], args.season)
    data = [{"league_id": l["league_id"], "name": (l.get("name") or "").strip(), "season": l.get("season"),
             "status": l.get("status"), "total_rosters": l.get("total_rosters")} for l in leagues]
    out = ["%s's NFL leagues (%d):" % (user.get("display_name") or username, len(data))]
    for d in data:
        out.append("  %s  %s (%s teams, %s)" % (d["league_id"], d["name"], d["total_rosters"], d["status"]))
    emit(args, data, out)


def cmd_rosters(args):
    lg = require_league(args)
    players = load_players(args.refresh)
    rosters = lg.rosters
    if args.team and args.team.lower() == "me":
        if lg.me is None:
            die("can't tell which team is yours. Set SLEEPER_USERNAME or pass --username.")
        rosters = [r for r in rosters if r["roster_id"] == lg.me]
    elif args.team:
        q = args.team.lower()
        rosters = [r for r in rosters if q in lg.team(r["roster_id"]).lower()
                   or q in lg.owner_names[r["roster_id"]].lower() or q == str(r["roster_id"])]
        if not rosters:
            die("no team matching '%s'. Run the `league` command to list teams." % args.team)
    data, out = [], []
    for r in rosters:
        starters = [p for p in (r.get("starters") or []) if p != "0"]
        reserve = r.get("reserve") or []
        taxi = r.get("taxi") or []
        bench = [p for p in (r.get("players") or []) if p not in starters and p not in reserve and p not in taxi]

        def rows(ids, role):
            return [{"player_id": pid, "name": pname(players.get(pid), pid),
                     "position": (players.get(pid) or {}).get("position"),
                     "nfl_team": (players.get(pid) or {}).get("team"),
                     "injury_status": (players.get(pid) or {}).get("injury_status"),
                     "role": role} for pid in ids]
        entry = {"roster_id": r["roster_id"], "team": lg.team(r["roster_id"]), "is_me": r["roster_id"] == lg.me,
                 "owner": lg.owner_names[r["roster_id"]],
                 "players": rows(starters, "starter") + rows(bench, "bench")
                 + rows(reserve, "IR") + rows(taxi, "taxi")}
        data.append(entry)
        out.append("== %s (%s)%s ==" % (entry["team"], entry["owner"], " <- you" if r["roster_id"] == lg.me else ""))
        for label, ids in (("Starters", starters), ("Bench", bench), ("IR", reserve), ("Taxi", taxi)):
            if ids:
                out.append("%s:" % label)
                for pid in ids:
                    out.append("  " + pdesc(players.get(pid), pid))
        out.append("")
    emit(args, data, out)


def cmd_available(args):
    lg = require_league(args)
    players = load_players(args.refresh)
    allowed = lg.positions()
    if args.pos:
        wanted = {p.strip().upper() for p in args.pos.split(",")}
        allowed = allowed & wanted
        if not allowed:
            die("position(s) %s not used in this league (league uses: %s)"
                % (args.pos, ", ".join(sorted(lg.positions()))))
    cands = []
    for pid, p in players.items():
        if pid in lg.owner_of or not p.get("active") or p.get("status") == "Inactive":
            continue
        if p.get("position") not in allowed or not p.get("team"):
            continue
        cands.append((p.get("search_rank") or 9999999, pid, p))
    cands.sort(key=lambda x: x[0])
    cands = cands[:args.limit]
    data = [{"player_id": pid, "name": pname(p, pid), "position": p.get("position"),
             "nfl_team": p.get("team"), "injury_status": p.get("injury_status"),
             "search_rank": rank} for rank, pid, p in cands]
    out = ["Top %d available (%s), by Sleeper search rank:" % (len(data), ",".join(sorted(allowed)))]
    for i, (rank, pid, p) in enumerate(cands, 1):
        out.append("%3d. %s" % (i, pdesc(p, pid)))
    emit(args, data, out)


def describe_trade(t, lg, players):
    """Per-team 'received' / 'sent' lists for a trade."""
    got, gave = {}, {}
    for pid, rid in (t.get("adds") or {}).items():
        got.setdefault(rid, []).append(pname(players.get(pid), pid))
    for pid, rid in (t.get("drops") or {}).items():
        gave.setdefault(rid, []).append(pname(players.get(pid), pid))
    for pk in t.get("draft_picks") or []:
        label = "%s R%s pick" % (pk.get("season"), pk.get("round"))
        if pk.get("roster_id") != pk.get("owner_id"):
            label += " (orig. %s)" % lg.team(pk.get("roster_id"))
        got.setdefault(pk.get("owner_id"), []).append(label)
        gave.setdefault(pk.get("previous_owner_id"), []).append(label)
    for wb in t.get("waiver_budget") or []:
        label = "$%s FAAB" % wb.get("amount")
        got.setdefault(wb.get("receiver"), []).append(label)
        gave.setdefault(wb.get("sender"), []).append(label)
    return got, gave


def cmd_transactions(args):
    lg = require_league(args)
    players = load_players(args.refresh)
    st, cur = current_week()
    week = args.week or cur
    txs = http_get("/league/%s/transactions/%d" % (lg.id, week)) or []
    txs = [t for t in txs if t.get("status") == "complete"]
    txs.sort(key=lambda t: t.get("status_updated") or t.get("created") or 0, reverse=True)
    data = []
    out = ["Week %d transactions (%d completed):" % (week, len(txs))]
    for t in txs:
        ts = t.get("status_updated") or t.get("created") or 0
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts / 1000)) if ts else "?"
        kind = t.get("type")
        rec = {"type": kind, "time": when, "roster_ids": t.get("roster_ids")}
        if kind == "trade":
            got, gave = describe_trade(t, lg, players)
            rec["teams"] = {lg.team(rid): {"received": got.get(rid, []), "sent": gave.get(rid, [])}
                            for rid in (t.get("roster_ids") or [])}
            out.append("[%s] TRADE" % when)
            for rid in t.get("roster_ids") or []:
                out.append("  %s receives: %s" % (lg.team(rid), ", ".join(got.get(rid, [])) or "nothing"))
                out.append("  %s sends:    %s" % (lg.team(rid), ", ".join(gave.get(rid, [])) or "nothing"))
        else:
            rid = (t.get("roster_ids") or [None])[0]
            adds = [pname(players.get(p), p) for p in (t.get("adds") or {})]
            drops = [pname(players.get(p), p) for p in (t.get("drops") or {})]
            bid = (t.get("settings") or {}).get("waiver_bid")
            rec.update({"team": lg.team(rid), "added": adds, "dropped": drops, "waiver_bid": bid})
            line = "[%s] %s %s:" % (when, kind.upper().replace("_", " "), lg.team(rid))
            if adds:
                line += " +" + ", +".join(adds)
            if drops:
                line += " -" + ", -".join(drops)
            if bid:
                line += " ($%s)" % bid
            out.append(line)
        data.append(rec)
    if not txs:
        out.append("  (none)")
    emit(args, data, out)


def cmd_matchups(args):
    lg = require_league(args)
    st, cur = current_week()
    week = args.week or cur
    ms = http_get("/league/%s/matchups/%d" % (lg.id, week)) or []
    groups = {}
    for m in ms:
        groups.setdefault(m.get("matchup_id"), []).append(m)
    data, out = [], ["Week %d matchups:" % week]
    for mid in sorted(groups, key=lambda x: (x is None, x)):
        g = groups[mid]
        data.append({"matchup_id": mid, "teams": [{"team": lg.team(m["roster_id"]),
                                                  "points": m.get("points", 0)} for m in g]})
        if len(g) == 2:
            a, b = g
            out.append("  %-26s %7.2f  vs  %-7.2f %s" % (lg.team(a["roster_id"])[:26], a.get("points") or 0,
                                                       b.get("points") or 0, lg.team(b["roster_id"])))
        else:
            for m in g:
                out.append("  %-26s %7.2f  (no opponent)" % (lg.team(m["roster_id"])[:26], m.get("points") or 0))
    if not ms:
        out.append("  (no matchups for this week)")
    emit(args, data, out)


def cmd_trending(args):
    lg = require_league(args)
    players = load_players(args.refresh)
    rows = http_get("/players/nfl/trending/%s?lookback_hours=%d&limit=%d"
                    % (args.type, args.hours, args.limit)) or []
    data, out = [], ["Trending %ss, last %dh (count = leagues on Sleeper):" % (args.type, args.hours)]
    for i, r in enumerate(rows, 1):
        pid = r["player_id"]
        p = players.get(pid)
        owner = lg.owner_of.get(pid)
        status = "owned by %s" % lg.label(owner) if owner else "AVAILABLE"
        data.append({"player_id": pid, "name": pname(p, pid), "position": (p or {}).get("position"),
                     "nfl_team": (p or {}).get("team"), "injury_status": (p or {}).get("injury_status"),
                     "count": r.get("count"), "available": owner is None,
                     "owner": lg.team(owner) if owner else None})
        out.append("%3d. %-40s %7d  %s" % (i, pdesc(p, pid), r.get("count", 0), status))
    emit(args, data, out)


def cmd_player(args):
    lg = require_league(args)
    players = load_players(args.refresh)
    q = args.name.lower().strip()
    names = {}
    for pid, p in players.items():
        n = pname(p, pid).lower()
        if n.startswith("unknown"):
            continue
        # prefer active players on name collisions
        if n not in names or (p.get("active") and not players[names[n]].get("active")):
            names[n] = pid
    matches = [n for n in names if q == n] or [n for n in names if q in n]
    if not matches:
        matches = difflib.get_close_matches(q, list(names), n=5, cutoff=0.6)
    if not matches:
        die("no player found matching '%s'" % args.name)
    matches.sort(key=lambda n: (not players[names[n]].get("active"),
                                players[names[n]].get("search_rank") or 9999999))
    matches = matches[:3]
    data, out = [], []
    for n in matches:
        pid = names[n]
        p = players[pid]
        owner = lg.owner_of.get(pid)
        d = {
            "player_id": pid, "name": pname(p, pid), "position": p.get("position"),
            "fantasy_positions": p.get("fantasy_positions"), "nfl_team": p.get("team"),
            "number": p.get("number"), "age": p.get("age"), "years_exp": p.get("years_exp"),
            "status": p.get("status"), "injury_status": p.get("injury_status"),
            "injury_body_part": p.get("injury_body_part"), "injury_notes": p.get("injury_notes"),
            "injury_start_date": p.get("injury_start_date"),
            "depth_chart_position": p.get("depth_chart_position"),
            "depth_chart_order": p.get("depth_chart_order"),
            "search_rank": p.get("search_rank"),
            "owner": lg.team(owner) if owner else None, "available": owner is None,
        }
        data.append(d)
        out.append("%s - %s %s #%s" % (d["name"], d["position"], d["nfl_team"] or "FA", d["number"] or "?"))
        out.append("  Age %s, exp %s yrs, status %s" % (d["age"], d["years_exp"], d["status"]))
        inj = d["injury_status"] or "Healthy (per Sleeper)"
        extra = ", ".join(str(x) for x in (d["injury_body_part"], d["injury_notes"]) if x)
        out.append("  Injury: %s%s%s" % (inj, " - " + extra if extra else "",
                                         " (since %s)" % d["injury_start_date"] if d["injury_start_date"] else ""))
        out.append("  Depth chart: %s %s" % (d["depth_chart_position"] or "?",
                                             d["depth_chart_order"] if d["depth_chart_order"] is not None else ""))
        out.append("  League: " + ("owned by %s" % lg.label(owner) if owner else "AVAILABLE (unrostered)"))
        out.append("")
    emit(args, data, out)


# --------------------------------------------------------------------- main

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--username", help="Sleeper username (default: $SLEEPER_USERNAME); finds your league and your team")
    common.add_argument("--league", help="Sleeper league ID (default: $SLEEPER_LEAGUE_ID)")
    common.add_argument("--json", action="store_true", help="structured JSON output")
    common.add_argument("--refresh", action="store_true", help="force refetch of the players cache")

    ap = argparse.ArgumentParser(description="Sleeper fantasy football CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, parents=[common])
        sp.set_defaults(fn=fn)
        return sp

    sp = add("leagues", cmd_leagues, "list a user's leagues for a season")
    sp.add_argument("--season", help="default: current season")
    add("league", cmd_league, "league summary, scoring, teams and records")
    sp = add("rosters", cmd_rosters, "team rosters")
    sp.add_argument("--team", help="team name/owner/roster id (substring), or \"me\" with a username set")
    sp = add("available", cmd_available, "unrostered active players")
    sp.add_argument("--pos", help="position(s), comma-separated, e.g. RB or WR,TE")
    sp.add_argument("--limit", type=int, default=25)
    sp = add("transactions", cmd_transactions, "completed trades, waivers, free-agent moves")
    sp.add_argument("--week", type=int)
    sp = add("matchups", cmd_matchups, "weekly pairings with points")
    sp.add_argument("--week", type=int)
    sp = add("trending", cmd_trending, "trending adds/drops with league availability")
    sp.add_argument("--type", choices=["add", "drop"], default="add")
    sp.add_argument("--hours", type=int, default=24)
    sp.add_argument("--limit", type=int, default=25)
    sp = add("player", cmd_player, "fuzzy player lookup")
    sp.add_argument("name")
    return ap


def main():
    args = build_parser().parse_args()
    try:
        args.fn(args)
    except SleeperError as e:
        die(str(e))
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
