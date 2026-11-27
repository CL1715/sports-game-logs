"""Build site/nba.json and site/nfl.json from open box-score data.

NBA: hoopR NBA dataset (ESPN box scores)  https://github.com/sportsdataverse/hoopR-nba-data
NFL: nflverse weekly player stats + schedule https://github.com/nflverse

Run: python scripts/build_data.py site
Set HOOPR_DIR / NFL_DIR to local folders to build from downloaded copies instead.
"""
import datetime as dt
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd

OUTDIR = sys.argv[1] if len(sys.argv) > 1 else "site"
SEASONS = 3  # current season + two before it
TODAY = dt.date.today()
ET = ZoneInfo("America/New_York")


def get(url, local_dir=None, name=None, csv=False):
    """Read a parquet/csv from a URL (or a local folder). Returns None when missing."""
    if local_dir:
        f = os.path.join(local_dir, name)
        if not os.path.exists(f):
            return None
        return pd.read_csv(f, low_memory=False) if csv else pd.read_parquet(f)
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return pd.read_csv(io.BytesIO(raw), low_memory=False) if csv else pd.read_parquet(io.BytesIO(raw))


def num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def num1(v):  # one decimal (fantasy points)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    return round(float(v), 1)


def defense_vs_position(players, team_count, games, cur_season, buckets, stats):
    """Per-game totals each defense allowed to each position bucket this season, with ranks.

    stats: {bucket: [(key, fn(row) -> value), ...]}; rank 1 = allows the most."""
    tot = {}  # (defense team, game) -> bucket -> stat sums
    for p in players:
        b = p["b"]
        if b not in stats:
            continue
        for r in p["g"]:
            if len(r) <= 7 or games[r[0]][1] != cur_season:
                continue
            d = tot.setdefault((r[2], r[0]), {}).setdefault(b, [0.0] * len(stats[b]))
            for i, (_, fn) in enumerate(stats[b]):
                d[i] += fn(r)
    gp = {}  # games each defense has played this season
    for (t, g) in tot:
        gp.setdefault(t, set()).add(g)
    out = {}
    for b in buckets:
        k = len(stats[b])
        sums = [[0.0] * k for _ in range(team_count)]
        for (t, g), d in tot.items():
            if b in d:
                for i in range(k):
                    sums[t][i] += d[b][i]
        n = [len(gp.get(t, ())) for t in range(team_count)]
        avgs = [[round(sums[t][i] / n[t], 1) if n[t] else None for i in range(k)] for t in range(team_count)]
        ranks = [[None] * k for _ in range(team_count)]
        lg = []
        for i in range(k):
            vals = sorted(((avgs[t][i], t) for t in range(team_count) if avgs[t][i] is not None), reverse=True)
            for rk, (_, t) in enumerate(vals, 1):
                ranks[t][i] = rk
            lg.append(round(sum(v for v, _ in vals) / len(vals), 1) if vals else None)
        out[b] = {"k": [key for key, _ in stats[b]], "avg": avgs, "rank": ranks, "lg": lg, "n": n}
    return out


# ---------------------------------------------------------------- NBA
def build_nba():
    raw = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba"
    loc = os.environ.get("HOOPR_DIR")

    def f(path):
        return get(f"{raw}/{path}", loc, path)

    season = TODAY.year + 1 if TODAY.month >= 8 else TODAY.year  # "2027" = 2026-27
    sch = f(f"schedules/parquet/nba_schedule_{season}.parquet")
    cur = f(f"player_box/parquet/player_box_{season}.parquet")
    if sch is None or cur is None or len(cur) == 0:
        season -= 1
        sch = f(f"schedules/parquet/nba_schedule_{season}.parquet")
        cur = f(f"player_box/parquet/player_box_{season}.parquet")
    boxes = [cur] + [b for b in (f(f"player_box/parquet/player_box_{y}.parquet")
                                 for y in range(season - SEASONS + 1, season)) if b is not None]
    box = pd.concat(boxes, ignore_index=True)
    box = box[box.season_type.isin([2, 3, 5])]
    ros = f(f"rosters/parquet/rosters_{season}.parquet")

    teams = {}
    for r in sch.itertuples():
        for tid, a, n, c in ((r.home_id, r.home_abbreviation, r.home_display_name, r.home_color),
                             (r.away_id, r.away_abbreviation, r.away_display_name, r.away_color)):
            teams.setdefault(int(tid), {"a": str(a), "n": str(n), "c": str(c or "555555")})
    # the 30 real franchises: teams in this season's box scores (drops All-Star and exhibition teams)
    real = set(box[box.season == season].team_id.astype(int)) or set(box.team_id.astype(int))
    teams = {t: v for t, v in teams.items() if t in real}
    ids = sorted(teams, key=lambda t: teams[t]["a"])
    tix = {t: i for i, t in enumerate(ids)}
    box = box[box.team_id.isin(teams) & box.opponent_team_id.isin(teams)]

    curbox = box[box.season == season].sort_values("game_date_time")
    pinfo = {}
    if ros is not None:
        for r in ros.itertuples():
            pinfo[int(r.athlete_id)] = {"n": r.display_name, "t": int(r.team_id),
                                        "p": r.position_abbreviation or "", "j": str(r.jersey or "")}
    for r in curbox.drop_duplicates("athlete_id", keep="last").itertuples():
        a = int(r.athlete_id)
        pinfo.setdefault(a, {"n": r.athlete_display_name, "t": int(r.team_id),
                             "p": r.athlete_position_abbreviation or "", "j": str(r.athlete_jersey or "")})
        pinfo[a]["t"] = int(r.team_id)  # latest team this season
    pinfo = {a: v for a, v in pinfo.items() if v["t"] in tix}

    games = box.drop_duplicates("game_id")[["game_id", "game_date", "season", "season_type"]].sort_values(["game_date", "game_id"])
    gix = {int(g): i for i, g in enumerate(games.game_id)}
    games_out = [[str(r.game_date), int(r.season), int(r.season_type)] for r in games.itertuples()]

    cols = ["MIN", "PTS", "REB", "OREB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "PF", "PM"]
    logs = {}
    for r in box[box.athlete_id.isin(list(pinfo))].sort_values("game_date_time").itertuples():
        row = [gix[int(r.game_id)], tix[int(r.team_id)], tix[int(r.opponent_team_id)],
               1 if r.home_away == "home" else 0, 1 if r.team_winner else 0, int(r.team_score), int(r.opponent_team_score)]
        if not r.did_not_play:
            try:
                pmv = int(str(r.plus_minus).replace("+", ""))
            except ValueError:
                pmv = 0
            row += [num(r.minutes), num(r.points), num(r.rebounds), num(r.offensive_rebounds), num(r.assists),
                    num(r.steals), num(r.blocks), num(r.turnovers), num(r.field_goals_made), num(r.field_goals_attempted),
                    num(r.three_point_field_goals_made), num(r.three_point_field_goals_attempted),
                    num(r.free_throws_made), num(r.free_throws_attempted), num(r.fouls), pmv]
        logs.setdefault(int(r.athlete_id), []).append(row)

    def bucket(p):
        return {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}.get(p)

    players = sorted(({"id": a, "n": v["n"], "t": tix[v["t"]], "p": v["p"], "b": bucket(v["p"]), "j": v["j"],
                       "g": logs.get(a, [])} for a, v in pinfo.items()), key=lambda p: p["n"])

    c = {k: i + 7 for i, k in enumerate(cols)}
    st = [("PTS", lambda r: r[c["PTS"]]), ("REB", lambda r: r[c["REB"]]), ("AST", lambda r: r[c["AST"]]),
          ("3PM", lambda r: r[c["3PM"]]), ("PRA", lambda r: r[c["PTS"]] + r[c["REB"]] + r[c["AST"]])]
    dvp = defense_vs_position(players, len(ids), games_out, season, ["G", "F", "C"], {"G": st, "F": st, "C": st})

    up = sch[sch.status_type_completed == False].sort_values("date")  # noqa: E712
    sched = [[str(r.date), tix[int(r.home_id)], tix[int(r.away_id)]] for r in up.itertuples()
             if int(r.home_id) in tix and int(r.away_id) in tix]
    through = str(curbox.game_date.max()) if len(curbox) else str(box.game_date.max())
    last = curbox.groupby("team_id").game_date.max().astype(str).to_dict()
    for t in ids:
        teams[t]["l"] = last.get(t, "")
    return {"league": "nba", "season": season, "through": through, "teams": [teams[t] for t in ids],
            "games": games_out, "cols": cols, "players": players, "sched": sched, "dvp": dvp}


# ---------------------------------------------------------------- NFL
NFL_TEAMS = {
    "ARI": ("Arizona Cardinals", "97233f"), "ATL": ("Atlanta Falcons", "a71930"), "BAL": ("Baltimore Ravens", "241773"),
    "BUF": ("Buffalo Bills", "00338d"), "CAR": ("Carolina Panthers", "0085ca"), "CHI": ("Chicago Bears", "0b162a"),
    "CIN": ("Cincinnati Bengals", "fb4f14"), "CLE": ("Cleveland Browns", "311d00"), "DAL": ("Dallas Cowboys", "003594"),
    "DEN": ("Denver Broncos", "fb4f14"), "DET": ("Detroit Lions", "0076b6"), "GB": ("Green Bay Packers", "203731"),
    "HOU": ("Houston Texans", "03202f"), "IND": ("Indianapolis Colts", "002c5f"), "JAX": ("Jacksonville Jaguars", "006778"),
    "KC": ("Kansas City Chiefs", "e31837"), "LA": ("Los Angeles Rams", "003594"), "LAC": ("Los Angeles Chargers", "0080c6"),
    "LV": ("Las Vegas Raiders", "000000"), "MIA": ("Miami Dolphins", "008e97"), "MIN": ("Minnesota Vikings", "4f2683"),
    "NE": ("New England Patriots", "002244"), "NO": ("New Orleans Saints", "9f8958"), "NYG": ("New York Giants", "0b2265"),
    "NYJ": ("New York Jets", "125740"), "PHI": ("Philadelphia Eagles", "004c54"), "PIT": ("Pittsburgh Steelers", "101820"),
    "SEA": ("Seattle Seahawks", "002244"), "SF": ("San Francisco 49ers", "aa0000"), "TB": ("Tampa Bay Buccaneers", "d50a0a"),
    "TEN": ("Tennessee Titans", "0c2340"), "WAS": ("Washington Commanders", "5a1414"),
}
NFL_ALIAS = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}


def build_nfl():
    rel = "https://github.com/nflverse/nflverse-data/releases/download/stats_player"
    loc = os.environ.get("NFL_DIR")
    season = TODAY.year if TODAY.month >= 6 else TODAY.year - 1
    frames = []
    for y in range(season - SEASONS + 1, season + 1):
        name = f"stats_player_week_{y}.parquet"
        d = get(f"{rel}/{name}", loc, name)
        if d is not None:
            frames.append(d)
    st = pd.concat(frames, ignore_index=True)
    if not (st.season == season).any():
        season -= 1
    st = st[st.season >= season - SEASONS + 1].copy()
    sch = get("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", loc, "games.csv", csv=True)
    for col in ("home_team", "away_team"):
        sch[col] = sch[col].replace(NFL_ALIAS)
    for col in ("team", "opponent_team"):
        st[col] = st[col].replace(NFL_ALIAS)

    ids = sorted(NFL_TEAMS)
    tix = {t: i for i, t in enumerate(ids)}
    teams = [{"a": t, "n": NFL_TEAMS[t][0], "c": NFL_TEAMS[t][1]} for t in ids]

    st["position"] = st.position.replace({"FB": "RB"})
    st = st[st.position.isin(["QB", "RB", "WR", "TE"]) & st.team.isin(tix) & st.opponent_team.isin(tix)]
    sch = sch[sch.season >= season - SEASONS + 1]
    played = sch[sch.result.notna()]
    games = played[played.game_id.isin(set(st.game_id))].sort_values(["gameday", "game_id"])
    gix = {g: i for i, g in enumerate(games.game_id)}
    games_out = [[str(r.gameday), int(r.season), 2 if r.game_type == "REG" else 3, int(r.week)] for r in games.itertuples()]
    ginfo = {r.game_id: r for r in games.itertuples()}

    cols = ["CMP", "ATT", "PYD", "PTD", "INT", "SK", "CAR", "RYD", "RTD", "TGT", "REC", "RECYD", "RECTD", "FUML", "FPTS"]
    st = st[st.game_id.isin(gix)].sort_values(["season", "week"])
    logs, info = {}, {}
    for r in st.itertuples():
        g = ginfo[r.game_id]
        home = 1 if r.team == g.home_team else 0
        ts, os_ = (g.home_score, g.away_score) if home else (g.away_score, g.home_score)
        row = [gix[r.game_id], tix[r.team], tix[r.opponent_team], home, 1 if ts > os_ else 0, num(ts), num(os_),
               num(r.completions), num(r.attempts), num(r.passing_yards), num(r.passing_tds), num(r.passing_interceptions),
               num(r.sacks_suffered), num(r.carries), num(r.rushing_yards), num(r.rushing_tds), num(r.targets),
               num(r.receptions), num(r.receiving_yards), num(r.receiving_tds),
               num(r.rushing_fumbles_lost) + num(r.receiving_fumbles_lost) + num(r.sack_fumbles_lost),
               num1(r.fantasy_points_ppr)]
        logs.setdefault(r.player_id, []).append(row)
        info[r.player_id] = {"n": r.player_display_name, "t": tix[r.team], "p": r.position, "s": int(r.season)}

    # players who appeared in the last two seasons
    players = sorted(({"id": a, "n": v["n"], "t": v["t"], "p": v["p"], "b": v["p"], "j": "", "g": logs[a]}
                      for a, v in info.items() if v["s"] >= season - 1), key=lambda p: p["n"])

    c = {k: i + 7 for i, k in enumerate(cols)}

    def g(k):
        return lambda r: r[c[k]]

    rec = [("REC", g("REC")), ("RECYD", g("RECYD")), ("RECTD", g("RECTD")), ("FPTS", g("FPTS"))]
    dvp = defense_vs_position(players, len(ids), games_out, season, ["QB", "RB", "WR", "TE"], {
        "QB": [("PYD", g("PYD")), ("PTD", g("PTD")), ("RYD", g("RYD")), ("FPTS", g("FPTS"))],
        "RB": [("RYD", g("RYD")), ("REC", g("REC")), ("RECYD", g("RECYD")), ("FPTS", g("FPTS"))],
        "WR": rec, "TE": rec})

    up = sch[sch.result.isna() & (sch.season == season)].sort_values(["gameday", "gametime"])
    sched = []
    for r in up.itertuples():
        if r.home_team not in tix or r.away_team not in tix:
            continue
        gt = r.gametime if isinstance(r.gametime, str) and r.gametime else "13:00"
        t = dt.datetime.fromisoformat(f"{r.gameday}T{gt}").replace(tzinfo=ET)
        sched.append([t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), tix[r.home_team], tix[r.away_team]])
    cur = st[st.season == season]
    through = f"Week {int(cur.week.max())}" if len(cur) else ""
    cg = played[played.season == season]
    for tm in teams:
        ds = cg[(cg.home_team == tm["a"]) | (cg.away_team == tm["a"])].gameday
        tm["l"] = str(ds.max()) if len(ds) else ""
    return {"league": "nfl", "season": season, "through": through, "teams": teams,
            "games": games_out, "cols": cols, "players": players, "sched": sched, "dvp": dvp}


if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    for name, fn in (("nba", build_nba), ("nfl", build_nfl)):
        data = fn()
        with open(os.path.join(OUTDIR, f"{name}.json"), "w") as fh:
            json.dump(data, fh, separators=(",", ":"))
        print(f"{name}: season {data['season']}, {len(data['players'])} players, "
              f"{len(data['games'])} games, through {data['through']}")
