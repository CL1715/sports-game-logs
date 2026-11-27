"""Download the latest NBA box scores from the open hoopR dataset and build data.json.

Run: python scripts/build_data.py data.json
"""
import datetime as dt
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request

import pandas as pd

RAW = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba"
OUT = sys.argv[1] if len(sys.argv) > 1 else "data.json"
SEASONS_BACK = 3  # current season + two before it


LOCAL = os.environ.get("HOOPR_DIR")  # optional local checkout of hoopR-nba-data/nba, for testing


def fetch(path):
    if LOCAL:
        f = os.path.join(LOCAL, path)
        return pd.read_parquet(f) if os.path.exists(f) else None
    url = f"{RAW}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return pd.read_parquet(io.BytesIO(r.read()))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


today = dt.date.today()
# NBA season "2027" = 2026-27; a new season's files appear around October
latest = today.year + 1 if today.month >= 8 else today.year
season = latest
sch = fetch(f"schedules/parquet/nba_schedule_{season}.parquet")
cur_box = fetch(f"player_box/parquet/player_box_{season}.parquet")
if sch is None or cur_box is None or len(cur_box) == 0:
    season -= 1  # new season hasn't started yet
    sch = fetch(f"schedules/parquet/nba_schedule_{season}.parquet")
    cur_box = fetch(f"player_box/parquet/player_box_{season}.parquet")

boxes = [cur_box]
for y in range(season - SEASONS_BACK + 1, season):
    b = fetch(f"player_box/parquet/player_box_{y}.parquet")
    if b is not None:
        boxes.append(b)
box = pd.concat(boxes, ignore_index=True)
box = box[box.season_type.isin([2, 3, 5])]  # regular season, playoffs, play-in
ros = fetch(f"rosters/parquet/rosters_{season}.parquet")

# Teams: the 30 franchises on the schedule
teams = {}


def add_team(tid, abbr, name, color):
    tid = int(tid)
    if tid not in teams:
        teams[tid] = {"a": str(abbr), "n": str(name), "c": str(color or "555555")}


for r in sch.itertuples():
    add_team(r.home_id, r.home_abbreviation, r.home_display_name, r.home_color)
    add_team(r.away_id, r.away_abbreviation, r.away_display_name, r.away_color)
sched_ids = set(teams)
team_ids = sorted(sched_ids, key=lambda t: teams[t]["a"])
tix = {t: i for i, t in enumerate(team_ids)}
box = box[box.team_id.isin(sched_ids) & box.opponent_team_id.isin(sched_ids)]

# Players: on a current roster or played this season; team = latest team this season
cur = box[box.season == season].sort_values("game_date_time")
latest_team = cur.groupby("athlete_id").team_id.last().to_dict()
pinfo = {}
if ros is not None:
    for r in ros.itertuples():
        pinfo[int(r.athlete_id)] = {"n": r.display_name, "t": int(r.team_id),
                                    "p": r.position_abbreviation or "", "j": str(r.jersey or "")}
for r in cur.drop_duplicates("athlete_id", keep="last").itertuples():
    a = int(r.athlete_id)
    if a not in pinfo:
        pinfo[a] = {"n": r.athlete_display_name, "t": int(r.team_id),
                    "p": r.athlete_position_abbreviation or "", "j": str(r.athlete_jersey or "")}
for a, t in latest_team.items():
    if int(a) in pinfo:
        pinfo[int(a)]["t"] = int(t)
pinfo = {a: v for a, v in pinfo.items() if v["t"] in tix}

games = box.drop_duplicates("game_id")[["game_id", "game_date", "season", "season_type"]].sort_values("game_date")
gix = {int(g): i for i, g in enumerate(games.game_id)}
games_out = [[str(r.game_date), int(r.season), int(r.season_type)] for r in games.itertuples()]


def n(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    return int(round(v))


def pm(v):
    try:
        return int(str(v).replace("+", ""))
    except Exception:
        return 0


# row: game, team, opp, home, win, team score, opp score, starter,
#      min (-1 = DNP), pts, reb, oreb, ast, stl, blk, to, fgm, fga, 3pm, 3pa, ftm, fta, pf, +/-
logs = {}
sub = box[box.athlete_id.isin(list(pinfo.keys()))].sort_values("game_date_time")
for r in sub.itertuples():
    row = [gix[int(r.game_id)], tix[int(r.team_id)], tix[int(r.opponent_team_id)],
           1 if r.home_away == "home" else 0, 1 if r.team_winner else 0,
           int(r.team_score), int(r.opponent_team_score), 1 if r.starter else 0]
    if r.did_not_play:
        row += [-1]
    else:
        row += [n(r.minutes), n(r.points), n(r.rebounds), n(r.offensive_rebounds), n(r.assists),
                n(r.steals), n(r.blocks), n(r.turnovers), n(r.field_goals_made), n(r.field_goals_attempted),
                n(r.three_point_field_goals_made), n(r.three_point_field_goals_attempted),
                n(r.free_throws_made), n(r.free_throws_attempted), n(r.fouls), pm(r.plus_minus)]
    logs.setdefault(int(r.athlete_id), []).append(row)

players = sorted(
    ({"id": a, "n": v["n"], "t": tix[v["t"]], "p": v["p"], "j": v["j"], "g": logs.get(a, [])} for a, v in pinfo.items()),
    key=lambda p: p["n"])

up = sch[sch.status_type_completed == False].sort_values("date")  # noqa: E712
sched_out = [[str(r.date), tix[int(r.home_id)], tix[int(r.away_id)]] for r in up.itertuples()
             if int(r.home_id) in tix and int(r.away_id) in tix]

through = str(cur.game_date.max()) if len(cur) else str(box.game_date.max())
out = {"through": through, "teams": [teams[t] for t in team_ids], "games": games_out,
       "players": players, "sched": sched_out}
with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"season {season}: {len(players)} players, {len(games_out)} games, box scores through {through}")
