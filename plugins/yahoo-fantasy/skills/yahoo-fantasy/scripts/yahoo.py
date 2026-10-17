#!/usr/bin/env python3
"""Yahoo Fantasy basketball CLI (read-only, standard library only).

Credentials come from the environment or a .env file (see load_env). Run
`auth` once; tokens are cached and refreshed automatically.
"""
import argparse
import base64
import difflib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft  # noqa: E402  (local draft board, shared state helpers)

API = "https://fantasysports.yahooapis.com/fantasy/v2"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "yahoo-fantasy-skill")
TOKEN_FILE = os.path.join(CACHE_DIR, "token.json")
TIMEOUT = 30


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def load_env():
    """Fill os.environ from .env files without overriding real variables.

    Order: real environment, ./.env, ~/.config/claude-plugins/.env.
    """
    paths = [os.path.join(os.getcwd(), ".env"),
             os.path.join(os.path.expanduser("~"), ".config", "claude-plugins", ".env")]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("export "):
                        k = k[7:].strip()
                    v = v.strip().strip('"').strip("'")
                    if v and not os.environ.get(k):
                        os.environ[k] = v
        except OSError:
            pass


def need(name):
    v = os.environ.get(name)
    if not v:
        die("%s is not set. Add it to .env or ~/.config/claude-plugins/.env." % name)
    return v


# --------------------------------------------------------------- OAuth layer

def redirect_uri():
    return os.environ.get("YAHOO_REDIRECT_URI") or "oob"


def token_request(form):
    basic = base64.b64encode(
        ("%s:%s" % (need("YAHOO_CLIENT_ID"), need("YAHOO_CLIENT_SECRET"))).encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": "Basic " + basic,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        die("Yahoo token request failed (HTTP %d). The code may be expired or the app "
            "credentials wrong. Run `auth` again." % e.code)
    except (urllib.error.URLError, OSError) as e:
        die("Network error reaching Yahoo: %s" % e)
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    return tok


def access_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = json.load(f)
    except (OSError, ValueError):
        die("not signed in. Run `auth` first.")
    if time.time() >= tok.get("expires_at", 0):
        tok = token_request({"grant_type": "refresh_token",
                             "refresh_token": tok["refresh_token"],
                             "redirect_uri": redirect_uri()})
    return tok["access_token"]


def cmd_auth(a):
    if a.code:
        token_request({"grant_type": "authorization_code", "code": a.code.strip(),
                       "redirect_uri": redirect_uri()})
        print("Signed in. Token saved to %s." % TOKEN_FILE)
        return
    q = urllib.parse.urlencode({"client_id": need("YAHOO_CLIENT_ID"),
                                "redirect_uri": redirect_uri(),
                                "response_type": "code", "language": "en-us"})
    print("1. Open this link, sign in and approve access:\n\n   %s?%s\n" % (AUTH_URL, q))
    print("2. Yahoo shows a code (or redirects with ?code=... in the address bar).")
    print("3. Run: yahoo.py auth --code THE_CODE")


# ----------------------------------------------------------------- API layer

def get(path):
    sep = "&" if "?" in path else "?"
    req = urllib.request.Request(
        "%s%s%sformat=json" % (API, path, sep),
        headers={"Authorization": "Bearer " + access_token(),
                 "User-Agent": "yahoo-fantasy-skill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return flat(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            die("Yahoo rejected the token (401). Run `auth` again.")
        if e.code in (403, 404):
            die("Yahoo returned %d for %s. Check the league ID, and that the signed-in "
                "account is in the league." % (e.code, path))
        die("Yahoo API returned HTTP %d for %s" % (e.code, path))
    except (urllib.error.URLError, OSError) as e:
        die("Network error reaching Yahoo: %s" % e)


def flat(x):
    """Collapse Yahoo's JSON (lists of one-key dicts, numeric-key maps) into plain structures."""
    if isinstance(x, list):
        items = [flat(i) for i in x]
        if items and all(isinstance(i, dict) for i in items):
            out = {}
            for i in items:
                out.update(i)
            return out
        return items
    if isinstance(x, dict):
        keys = [k for k in x if k != "count"]
        if keys and all(k.isdigit() for k in keys):
            return [flat(x[k]) for k in sorted(keys, key=int)]
        return {k: flat(v) for k, v in x.items()}
    return x


def find(x, key):
    """First value for `key` anywhere in a nested structure."""
    if isinstance(x, dict):
        if key in x:
            return x[key]
        for v in x.values():
            r = find(v, key)
            if r is not None:
                return r
    elif isinstance(x, list):
        for v in x:
            r = find(v, key)
            if r is not None:
                return r
    return None


def collect(x, key):
    """Every value for `key` anywhere in a nested structure."""
    out = []
    if isinstance(x, dict):
        for k, v in x.items():
            if k == key:
                out.append(v)
            else:
                out.extend(collect(v, key))
    elif isinstance(x, list):
        for v in x:
            out.extend(collect(v, key))
    return out


def league_key(a):
    lid = a.league or os.environ.get("YAHOO_LEAGUE_ID")
    if not lid:
        die("no league. Set YAHOO_LEAGUE_ID or pass --league.")
    if ".l." in lid:
        return lid
    game = find(get("/game/nba"), "game_key")
    return "%s.l.%s" % (game, lid)


def teams(lk):
    """List of team dicts (team_key, name, is_owned_by_current_login, ...)."""
    rows = find(get("/league/%s/teams" % lk), "teams") or []
    return [t.get("team", t) for t in rows if isinstance(t, dict)]


def player_line(p):
    return "%-24s %-10s %-4s %s" % (
        (p.get("name") or {}).get("full", "?"), p.get("display_position", ""),
        p.get("editorial_team_abbr", ""), p.get("status", ""))


# ------------------------------------------------------------------ commands

def cmd_league(a):
    lk = league_key(a)
    data = get("/league/%s/settings" % lk)
    lg = data.get("fantasy_content", data).get("league", data)
    print("%s  (%s)" % (lg.get("name", "?"), lk))
    print("Teams: %s | Scoring: %s | Draft: %s | Status: %s" % (
        lg.get("num_teams"), lg.get("scoring_type"), lg.get("draft_type") or find(lg, "draft_type"),
        lg.get("draft_status")))
    for key, label in (("draft_time", "Draft time"), ("max_teams", "Max teams"),
                       ("trade_end_date", "Trade deadline"), ("playoff_start_date", "Playoffs start")):
        v = find(lg, key)
        if v:
            print("%s: %s" % (label, v))
    slots = [rp["roster_position"] for rp in (find(lg, "roster_positions") or [])
             if isinstance(rp, dict) and "roster_position" in rp]
    print("Roster: " + ", ".join("%s x%s" % (s["position"], s["count"]) for s in slots))
    cats = [s["display_name"] for s in collect(find(lg, "stat_categories") or {}, "stat")
            if isinstance(s, dict) and "display_name" in s]
    if cats:
        print("Categories (%d): %s" % (len(cats), ", ".join(cats)))
    print("Teams:")
    for t in teams(lk):
        print("  %-30s %s%s" % (t.get("name", "?"), t.get("team_key", ""),
                                "  <- you" if str(t.get("is_owned_by_current_login")) == "1" else ""))


def cmd_standings(a):
    lk = league_key(a)
    rows = find(get("/league/%s/standings" % lk), "teams") or []
    for t in rows:
        t = t.get("team", t)
        s = t.get("team_standings", {})
        rec = s.get("outcome_totals", {})
        print("%2s. %-30s %s-%s-%s" % (s.get("rank", "?"), t.get("name", "?"),
                                       rec.get("wins"), rec.get("losses"), rec.get("ties")))


def my_team_key(lk):
    for t in teams(lk):
        if str(t.get("is_owned_by_current_login")) == "1":
            return t["team_key"]
    die("couldn't find your team in this league.")


def cmd_roster(a):
    lk = league_key(a)
    tk = a.team or my_team_key(lk)
    if tk.isdigit():
        tk = "%s.t.%s" % (lk, tk)
    for p in find(get("/team/%s/roster" % tk), "players") or []:
        p = p.get("player", p)
        print("%-4s %s" % (p.get("selected_position", {}).get("position", ""), player_line(p)))


def cmd_free_agents(a):
    lk = league_key(a)
    q = "status=FA;sort=AR;count=%d" % a.limit
    if a.pos:
        q += ";position=" + a.pos
    for p in find(get("/league/%s/players;%s" % (lk, q)), "players") or []:
        print(player_line(p.get("player", p)))


def cmd_matchup(a):
    lk = league_key(a)
    for m in find(get("/league/%s/scoreboard" % lk), "matchups") or []:
        m = m.get("matchup", m)
        names = [t.get("name", "?") for t in collect(m, "team") if isinstance(t, dict) and "name" in t]
        print("%s  (week %s)" % ("  vs  ".join(names), m.get("week")))


def resolve_players(keys):
    names = {}
    for i in range(0, len(keys), 25):
        chunk = keys[i:i + 25]
        for p in find(get("/players;player_keys=" + ",".join(chunk)), "players") or []:
            p = p.get("player", p)
            names[p.get("player_key")] = (p.get("name") or {}).get("full", "?")
    return names


def cmd_draft_results(a):
    lk = league_key(a)
    results = [r.get("draft_result", r) for r in
               (find(get("/league/%s/draftresults" % lk), "draft_results") or [])]
    results = [r for r in results if r.get("player_key")]
    if not results:
        print("No picks yet.")
        return
    names = resolve_players([r["player_key"] for r in results])
    tnames = {t["team_key"]: t.get("name", "?") for t in teams(lk)}
    for r in results[-a.last:]:
        print("#%-3s rd %-2s %-28s %s" % (r.get("pick"), r.get("round"),
                                          tnames.get(r.get("team_key"), r.get("team_key")),
                                          names.get(r["player_key"], "?")))
    if a.sync:
        s = draft.load()
        ranked = [p["name"] for p in s["players"]]
        s["picks"] = []
        for r in sorted(results, key=lambda r: int(r["pick"])):
            n = int(r["pick"])
            nm = names.get(r["player_key"], "?")
            m = difflib.get_close_matches(nm, ranked, n=1, cutoff=0.8)
            s["picks"].append({"n": n, "slot": draft.team_on_clock(s, n), "player": m[0] if m else nm})
        draft.save(s)
        print("Synced %d picks into the local board." % len(results))


def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", help="league ID or full key (default: YAHOO_LEAGUE_ID)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("auth")
    p.add_argument("--code")
    p.set_defaults(fn=cmd_auth)
    sub.add_parser("league").set_defaults(fn=cmd_league)
    sub.add_parser("standings").set_defaults(fn=cmd_standings)
    p = sub.add_parser("roster")
    p.add_argument("--team", help="team key or team number (default: yours)")
    p.set_defaults(fn=cmd_roster)
    p = sub.add_parser("free-agents")
    p.add_argument("--pos")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(fn=cmd_free_agents)
    sub.add_parser("matchup").set_defaults(fn=cmd_matchup)
    p = sub.add_parser("draft-results")
    p.add_argument("--last", type=int, default=15)
    p.add_argument("--sync", action="store_true", help="write picks into the local draft board")
    p.set_defaults(fn=cmd_draft_results)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
