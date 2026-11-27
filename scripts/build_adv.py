"""Build site/nba_adv.json and site/nfl_adv.json: advanced stats for the player pages' Advanced tab.

NBA: rate stats from box scores (usage, true shooting, assist/rebound/turnover rates, per-36) and shot
     locations from the hoopR shots table (zones, shot chart, what each defense allows by zone).
NFL: nflverse weekly stats + play-by-play + snap counts + Next Gen Stats + PFR advanced + FTN charting.

Run after build_data.py:  python scripts/build_adv.py site
Set HOOPR_DIR / NFL_DIR to read local copies instead of downloading.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from build_data import get, TODAY  # noqa: E402

SITE = sys.argv[1] if len(sys.argv) > 1 else "site"


def r1(x, nd=1):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def pct_rank(values, lower_better=False):
    """Percentile (0-100) of each value within its list; None stays None."""
    arr = [v for v in values if v is not None]
    if len(arr) < 5:
        return [None] * len(values)
    s = sorted(arr)
    out = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        below = sum(1 for x in s if x < v)
        eq = sum(1 for x in s if x == v)
        p = (below + 0.5 * eq) / len(s) * 100
        out.append(round(100 - p if lower_better else p))
    return out


def add_percentiles(players, groups, metrics, qualify):
    """players: {id: {"g": group, "m": {metric: value}}}; writes p[metric] percentiles among qualified peers."""
    for g in groups:
        ids = [i for i, p in players.items() if p["g"] == g and qualify(p)]
        for key, lower in metrics:
            vals = [players[i]["m"].get(key) for i in ids]
            for i, pr in zip(ids, pct_rank(vals, lower)):
                players[i].setdefault("p", {})[key] = pr
        players_n = len(ids)
        for i in ids:
            players[i]["n"] = players_n


# ------------------------------------------------------------------ NBA
def build_nba():
    with open(os.path.join(SITE, "nba.json")) as f:
        base = json.load(f)
    season = base["season"]
    raw = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba"
    loc = os.environ.get("HOOPR_DIR")
    box = get(f"{raw}/player_box/parquet/player_box_{season}.parquet", loc, f"player_box/parquet/player_box_{season}.parquet")
    shots = get(f"{raw}/shots/parquet/shots_{season}.parquet", loc, f"shots/parquet/shots_{season}.parquet")
    box = box[box.season_type.isin([2, 3, 5]) & ~box.did_not_play.fillna(False)].copy()
    for c in ["minutes", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made",
              "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted", "offensive_rebounds",
              "defensive_rebounds", "rebounds", "assists", "turnovers", "points", "steals", "blocks"]:
        box[c] = pd.to_numeric(box[c], errors="coerce").fillna(0)
    team = box.groupby(["game_id", "team_id"]).agg(tmin=("minutes", "sum"), tfga=("field_goals_attempted", "sum"),
                                                   tfgm=("field_goals_made", "sum"), tfta=("free_throws_attempted", "sum"),
                                                   tto=("turnovers", "sum"), treb=("rebounds", "sum"),
                                                   toreb=("offensive_rebounds", "sum"), tdreb=("defensive_rebounds", "sum")).reset_index()
    opp = team.rename(columns={"team_id": "opp_id", "treb": "oreb_tot", "toreb": "o_oreb", "tdreb": "o_dreb"})[["game_id", "opp_id", "oreb_tot", "o_oreb", "o_dreb"]]
    b = box.merge(team, on=["game_id", "team_id"]).merge(opp, left_on=["game_id", "opponent_team_id"], right_on=["game_id", "opp_id"])
    bucket = {str(p["id"]): p["b"] for p in base["players"]}
    players = {}
    for aid, g in b.groupby("athlete_id"):
        aid = str(int(aid))
        if aid not in bucket or not bucket[aid]:
            continue
        mn = g.minutes.sum()
        if mn <= 0:
            continue
        fga, fta, to = g.field_goals_attempted.sum(), g.free_throws_attempted.sum(), g.turnovers.sum()
        tm_share = mn / (g.tmin.sum() / 5)
        m = {
            "mpg": mn / len(g),
            "usg": 100 * (fga + 0.44 * fta + to) / (tm_share * (g.tfga + 0.44 * g.tfta + g.tto).sum()) if tm_share else None,
            "ts": 100 * g.points.sum() / (2 * (fga + 0.44 * fta)) if fga + fta else None,
            "efg": 100 * (g.field_goals_made.sum() + 0.5 * g.three_point_field_goals_made.sum()) / fga if fga else None,
            "par3": 100 * g.three_point_field_goals_attempted.sum() / fga if fga else None,
            "ftr": 100 * fta / fga if fga else None,
            "ast": 100 * g.assists.sum() / (tm_share * g.tfgm.sum() - g.field_goals_made.sum()) if tm_share * g.tfgm.sum() - g.field_goals_made.sum() > 0 else None,
            "reb": 100 * g.rebounds.sum() / (tm_share * (g.treb + g.oreb_tot).sum()) if tm_share else None,
            "oreb": 100 * g.offensive_rebounds.sum() / (tm_share * (g.toreb + g.o_dreb).sum()) if tm_share else None,
            "tov": 100 * to / (fga + 0.44 * fta + to) if fga + fta + to else None,
            "p36": 36 * g.points.sum() / mn, "r36": 36 * g.rebounds.sum() / mn, "a36": 36 * g.assists.sum() / mn,
            "stk36": 36 * (g.steals.sum() + g.blocks.sum()) / mn,
        }
        players[aid] = {"g": bucket[aid], "m": {k: r1(v) for k, v in m.items()}, "gp": len(g)}
    metrics = [("mpg", False), ("usg", False), ("ts", False), ("efg", False), ("par3", False), ("ftr", False), ("ast", False),
               ("reb", False), ("oreb", False), ("tov", True), ("p36", False), ("r36", False), ("a36", False), ("stk36", False)]
    add_percentiles(players, ["G", "F", "C"], metrics, lambda p: p["gp"] >= 5 and (p["m"]["mpg"] or 0) >= 15)

    # shots: zones, chart, defense by zone
    shots = shots[~shots.type_text.fillna("").str.startswith("Free Throw")].copy()
    x, y = shots.coordinate_x.astype(float), shots.coordinate_y.astype(float)
    d = np.minimum(np.hypot(x - 41.75, y), np.hypot(x + 41.75, y))
    corner = (y.abs() >= 21.5) & (x.abs() >= 33)
    three = (shots.score_value == 3) | ((shots.score_value == 0) & ((corner & (d >= 21.5)) | (d >= 23.5)))
    zone = np.select([three & corner, three, d < 4, d < 10], ["c3", "ab3", "rim", "paint"], "mid")
    shots["zone"] = zone
    shots["made"] = shots.scoring_play.fillna(False).astype(bool)
    shots["ast"] = shots.made & shots.athlete_id_2.notna()
    # half-court coordinates: hx = feet from the baseline side of the hoop, hy = sideline offset
    near_pos = (x > 0)
    shots["hx"] = (47 - x.abs()).round(1)
    shots["hy"] = np.where(near_pos, -y, y).round(1)
    gteams = box.groupby("game_id").team_id.unique().to_dict()
    shots["def_id"] = [next((t for t in gteams.get(gid, []) if t != tid), None) for gid, tid in zip(shots.game_id, shots.team_id)]
    zones = ["rim", "paint", "mid", "c3", "ab3"]
    lg = shots.groupby("zone").agg(a=("made", "size"), m=("made", "sum"))
    league = {z: {"fg": r1(100 * lg.m[z] / lg.a[z]) if z in lg.index else None, "fr": r1(100 * lg.a[z] / lg.a.sum()) if z in lg.index else None} for z in zones}
    for aid, g in shots.groupby("athlete_id_1"):
        key = str(int(aid))
        if key not in players:
            continue
        tot = len(g)
        zs = {}
        for z in zones:
            gz = g[g.zone == z]
            if len(gz):
                zs[z] = {"a": int(len(gz)), "fr": r1(100 * len(gz) / tot), "fg": r1(100 * gz.made.mean()),
                         "as": r1(100 * gz.ast.sum() / gz.made.sum()) if gz.made.sum() else None}
        pts = g.tail(500)
        players[key]["z"] = zs
        players[key]["sh"] = [[float(a), float(b_), int(c)] for a, b_, c in zip(pts.hx, pts.hy, pts.made)]
    team_ids = {t["a"]: i for i, t in enumerate(base["teams"])}
    abbr_by_id = {}
    for r in box.drop_duplicates("team_id").itertuples():
        abbr_by_id[int(r.team_id)] = r.team_abbreviation
    defense = {}
    for tid, g in shots[shots.def_id.notna()].groupby("def_id"):
        ab = abbr_by_id.get(int(tid))
        if ab not in team_ids:
            continue
        tot = len(g)
        defense[team_ids[ab]] = {z: {"fg": r1(100 * g[g.zone == z].made.mean()) if (g.zone == z).any() else None,
                                     "fr": r1(100 * (g.zone == z).sum() / tot)} for z in zones}
    for z in zones:  # rank defenses by FG% allowed in each zone (1 = allows the highest)
        vals = sorted(((v[z]["fg"], t) for t, v in defense.items() if v[z]["fg"] is not None), reverse=True)
        for rk, (_, t) in enumerate(vals, 1):
            defense[t][z]["rk"] = rk
    return {"season": season, "players": players, "league": league, "defense": {str(k): v for k, v in defense.items()}}


# ------------------------------------------------------------------ NFL
def build_nfl():
    with open(os.path.join(SITE, "nfl.json")) as f:
        base = json.load(f)
    season = base["season"]
    rel = "https://github.com/nflverse/nflverse-data/releases/download"
    loc = os.environ.get("NFL_DIR")

    def dl(path):
        return get(f"{rel}/{path}", loc, os.path.basename(path))

    wk = dl(f"stats_player/stats_player_week_{season}.parquet")
    pbp = dl(f"pbp/play_by_play_{season}.parquet")
    snaps = dl(f"snap_counts/snap_counts_{season}.parquet")
    ngs_r, ngs_p, ngs_u = dl("nextgen_stats/ngs_receiving.parquet"), dl("nextgen_stats/ngs_passing.parquet"), dl("nextgen_stats/ngs_rushing.parquet")
    pfr_rec, pfr_pass, pfr_rush = (dl(f"pfr_advstats/advstats_week_{k}_{season}.parquet") for k in ("rec", "pass", "rush"))
    ftn = dl(f"ftn_charting/ftn_charting_{season}.parquet")
    xw = dl("players/players.parquet")
    alias = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}
    team_ix = {t["a"]: i for i, t in enumerate(base["teams"])}
    pos = {p["id"]: p["p"] for p in base["players"]}

    wk = wk[(wk.season_type == "REG") & wk.player_id.isin(pos.keys())].copy()
    wk["team"] = wk.team.replace(alias)
    pbp = pbp[(pbp.season_type == "REG")].copy()
    for c in ("posteam", "defteam"):
        pbp[c] = pbp[c].replace(alias)
    pfr2gsis = dict(zip(xw.pfr_id, xw.gsis_id)) if xw is not None else {}

    # FTN charting joined to play-by-play
    if ftn is not None:
        ftn = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
        pbp = pbp.merge(ftn[["game_id", "play_id", "is_play_action", "is_contested_ball", "is_catchable_ball", "is_drop",
                             "is_created_reception", "is_screen_pass", "n_defense_box"]], on=["game_id", "play_id"], how="left")

    tg = pbp[(pbp.play_type == "pass") & pbp.receiver_player_id.notna() & (pbp.sack != 1)].copy()
    tg["depth"] = pd.cut(tg.air_yards.fillna(0), [-100, -0.1, 9.9, 19.9, 200], labels=["bh", "sh", "int", "dp"])
    tg["rz"] = tg.yardline_100 <= 20
    tg["ez"] = tg.air_yards >= tg.yardline_100
    team_tg = tg.groupby("posteam").size()
    team_rz = tg[tg.rz].groupby("posteam").size()
    team_3d = tg[tg.down == 3].groupby("posteam").size()
    ru = pbp[(pbp.play_type == "run") & pbp.rusher_player_id.notna()].copy()
    team_car = ru.groupby("posteam").size()
    team_gl = ru[ru.yardline_100 <= 10].groupby("posteam").size()
    team_rzc = ru[ru.yardline_100 <= 20].groupby("posteam").size()

    snaps = snaps[snaps.game_type == "REG"].copy() if snaps is not None else None
    if snaps is not None:
        snaps["gsis"] = snaps.pfr_player_id.map(pfr2gsis)
    ng_season = lambda df: df[(df.season == season) & (df.week == 0)] if df is not None else None  # noqa: E731
    nr, npas, nru = ng_season(ngs_r), ng_season(ngs_p), ng_season(ngs_u)

    def pfr_sum(df, cols):
        if df is None:
            return {}
        df = df[df.game_type == "REG"].copy()
        df["gsis"] = df.pfr_player_id.map(pfr2gsis)
        return df.groupby("gsis")[cols].sum(min_count=1).to_dict("index")
    prec = pfr_sum(pfr_rec, ["receiving_drop", "receiving_broken_tackles"])
    prush = pfr_sum(pfr_rush, ["carries", "rushing_yards_before_contact", "rushing_yards_after_contact", "rushing_broken_tackles"])
    ppass = pfr_sum(pfr_pass, ["times_pressured", "times_blitzed", "passing_bad_throws", "times_sacked", "times_hurried", "times_hit"])

    players = {}
    for pid, g in wk.groupby("player_id"):
        p = pos.get(pid)
        tm = g.team.iloc[-1]
        m, w = {}, []
        sn = snaps[snaps.gsis == pid] if snaps is not None else None
        m["snap"] = r1(100 * sn.offense_pct.mean()) if sn is not None and len(sn) else None
        tgt, car = g.targets.sum(), g.carries.sum()
        # team-relative shares over the games he played
        games = set(g.game_id)
        ttg = tg[tg.game_id.isin(games) & (tg.posteam == tm)]
        tru = ru[ru.game_id.isin(games) & (ru.posteam == tm)]
        mt = tg[tg.receiver_player_id == pid]
        mr = ru[ru.rusher_player_id == pid]
        if p in ("WR", "TE", "RB"):
            ay = g.receiving_air_yards.sum()
            team_ay = ttg.air_yards.clip(lower=0).sum()
            m.update({
                "tgt_g": tgt / len(g), "tshare": 100 * tgt / len(ttg) if len(ttg) else None,
                "ayshare": 100 * mt.air_yards.clip(lower=0).sum() / team_ay if team_ay else None,
                "adot": ay / tgt if tgt else None, "yacr": g.receiving_yards_after_catch.sum() / g.receptions.sum() if g.receptions.sum() else None,
                "catch": 100 * g.receptions.sum() / tgt if tgt else None, "epat": g.receiving_epa.sum() / tgt if tgt else None,
                "racr": g.receiving_yards.sum() / ay if ay > 0 else None, "fdr": 100 * g.receiving_first_downs.sum() / tgt if tgt else None,
                "rzshare": 100 * mt.rz.sum() / ttg.rz.sum() if ttg.rz.sum() else None, "ezt": int(mt.ez.sum()),
                "deep": 100 * (mt.depth == "dp").mean() if len(mt) else None,
                "mid": 100 * (mt.pass_location == "middle").mean() if len(mt) else None,
                "d3share": 100 * (mt.down == 3).sum() / (ttg.down == 3).sum() if (ttg.down == 3).sum() else None,
            })
            if m.get("tshare") is not None and m.get("ayshare") is not None:
                m["wopr"] = 1.5 * m["tshare"] / 100 + 0.7 * m["ayshare"] / 100
            if "is_contested_ball" in mt:
                ch = mt[mt.is_contested_ball.notna()]
                m["contested"] = 100 * ch.is_contested_ball.mean() if len(ch) else None
                m["catchable"] = 100 * ch.is_catchable_ball.mean() if len(ch) else None
                m["drop"] = 100 * ch.is_drop.sum() / max(1, ch.is_catchable_ball.sum()) if len(ch) else None
                m["screen"] = 100 * ch.is_screen_pass.mean() if len(ch) else None
            if nr is not None:
                x = nr[nr.player_gsis_id == pid]
                if len(x):
                    x = x.iloc[0]
                    m.update({"sep": x.avg_separation, "cush": x.avg_cushion, "yacoe": x.avg_yac_above_expectation})
            pr = prec.get(pid, {})
            m["btk"] = pr.get("receiving_broken_tackles")
            # target profile
            prof = {k: r1(100 * (mt.depth == k).mean()) for k in ("bh", "sh", "int", "dp")} if len(mt) else {}
            loc_ = {k: r1(100 * (mt.pass_location == k).mean()) for k in ("left", "middle", "right")} if len(mt) else {}
            players[pid] = {"prof": prof, "loc": loc_}
        if p in ("RB", "QB") or car >= 10:
            m.update({
                "car_g": car / len(g), "cshare": 100 * len(mr) / len(tru) if len(tru) else None,
                "gl": 100 * (mr.yardline_100 <= 10).sum() / (tru.yardline_100 <= 10).sum() if (tru.yardline_100 <= 10).sum() else None,
                "rzc": 100 * (mr.yardline_100 <= 20).sum() / (tru.yardline_100 <= 20).sum() if (tru.yardline_100 <= 20).sum() else None,
                "epar": mr.epa.mean() if len(mr) else None, "succ": 100 * (mr.epa > 0).mean() if len(mr) else None,
                "expl": 100 * (mr.yards_gained >= 10).mean() if len(mr) else None,
            })
            pr = prush.get(pid, {})
            if pr.get("carries"):
                m["ybc"] = pr["rushing_yards_before_contact"] / pr["carries"]
                m["yac_r"] = pr["rushing_yards_after_contact"] / pr["carries"]
                m["btk_r"] = pr.get("rushing_broken_tackles")
            if nru is not None:
                x = nru[nru.player_gsis_id == pid]
                if len(x):
                    x = x.iloc[0]
                    m.update({"ryoe": x.rush_yards_over_expected_per_att, "box8": x.percent_attempts_gte_eight_defenders, "eff": x.efficiency})
        if p == "QB":
            db = pbp[(pbp.passer_player_id == pid) | ((pbp.rusher_player_id == pid) & (pbp.qb_scramble == 1))]
            db = db[(db.qb_dropback == 1)]
            att = pbp[(pbp.passer_player_id == pid) & (pbp.pass_attempt == 1) & (pbp.sack != 1)]
            m.update({
                "dropbacks": len(db), "epadb": db.qb_epa.mean() if len(db) else None, "cpoe": att.cpoe.mean() if len(att) else None,
                "adot_q": att.air_yards.mean() if len(att) else None, "deep_q": 100 * (att.air_yards >= 20).mean() if len(att) else None,
                "sack": 100 * db.sack.mean() if len(db) else None, "scr": 100 * db.qb_scramble.mean() if len(db) else None,
                "pa": 100 * db.is_play_action.mean() if "is_play_action" in db and db.is_play_action.notna().any() else None,
            })
            pp = ppass.get(pid, {})
            if pp and len(db):
                m["press"] = 100 * (pp.get("times_pressured") or 0) / len(db)
                m["blitz"] = 100 * (pp.get("times_blitzed") or 0) / len(db)
                m["bad"] = 100 * (pp.get("passing_bad_throws") or 0) / max(1, len(att))
            if npas is not None:
                x = npas[npas.player_gsis_id == pid]
                if len(x):
                    x = x.iloc[0]
                    m.update({"ttt": x.avg_time_to_throw, "aggr": x.aggressiveness})
        # weekly usage trend
        for r in g.sort_values("week").itertuples():
            gg = tg[(tg.game_id == r.game_id) & (tg.posteam == tm)]
            rr = ru[(ru.game_id == r.game_id) & (ru.posteam == tm)]
            snp = sn[sn.week == r.week].offense_pct.mean() if sn is not None and len(sn) else None
            w.append([int(r.week), r1(100 * snp) if snp is not None and not pd.isna(snp) else None,
                      r1(100 * r.targets / len(gg)) if len(gg) else None, r1(100 * r.carries / len(rr)) if len(rr) else None])
        players.setdefault(pid, {})
        players[pid].update({"g": p, "m": {k: (r1(v, 2) if k in ("epat", "epar", "epadb", "wopr", "racr") else r1(v)) for k, v in m.items()},
                             "w": w, "gp": len(g), "tgt": int(tgt), "car": int(car)})
    metrics = {"WR": [("snap", 0), ("tshare", 0), ("ayshare", 0), ("wopr", 0), ("adot", 0), ("yacr", 0), ("catch", 0), ("epat", 0), ("rzshare", 0), ("sep", 0), ("yacoe", 0), ("contested", 0), ("drop", 1), ("fdr", 0), ("deep", 0), ("mid", 0), ("screen", 0), ("d3share", 0)],
               "RB": [("snap", 0), ("cshare", 0), ("tshare", 0), ("gl", 0), ("rzc", 0), ("epar", 0), ("succ", 0), ("expl", 0), ("ybc", 0), ("yac_r", 0), ("ryoe", 0), ("box8", 0), ("yacr", 0)],
               "QB": [("epadb", 0), ("cpoe", 0), ("adot_q", 0), ("deep_q", 0), ("ttt", 1), ("aggr", 0), ("press", 1), ("sack", 1), ("bad", 1), ("scr", 0), ("pa", 0)]}
    metrics["TE"] = metrics["WR"]
    for g_, ms in metrics.items():
        qual = {"WR": lambda p: p["tgt"] >= 20, "TE": lambda p: p["tgt"] >= 15, "RB": lambda p: p["car"] >= 30 or p["tgt"] >= 20,
                "QB": lambda p: (p["m"].get("dropbacks") or 0) >= 100}[g_]
        add_percentiles(players, [g_], [(k, bool(lo)) for k, lo in ms], qual)

    # role read for pass catchers (alignment itself isn't public; inferred from target depth and direction)
    for pid, p in players.items():
        m = p.get("m", {})
        if p.get("g") in ("WR", "TE") and p.get("tgt", 0) >= 10 and m.get("adot") is not None:
            adot, mid, deep, scr = m["adot"], m.get("mid") or 0, m.get("deep") or 0, m.get("screen") or 0
            if adot >= 13 or deep >= 25:
                role = ["Vertical / outside", "Deep targets and a high average depth, typical of an outside X or Z receiver."]
            elif adot <= 8.5 and (mid >= 25 or scr >= 12):
                role = ["Underneath / slot-style", "Short, middle-of-field and screen targets, the usage pattern slot receivers usually have."]
            elif adot <= 8.5:
                role = ["Short-area / possession", "Mostly short targets near the sideline: quick outs, hitches and checkdowns."]
            else:
                role = ["Intermediate / move", "A mix of depths, typical of a flanker or a move tight end."]
            p["role"] = role

    # team defense (for the matchup panel)
    dfn = {}
    pa = pbp[(pbp.qb_dropback == 1)]
    rr = pbp[(pbp.play_type == "run")]
    for tm, g in pa.groupby("defteam"):
        if tm not in team_ix:
            continue
        r_ = rr[rr.defteam == tm]
        att = g[(g.pass_attempt == 1) & (g.sack != 1)]
        dfn[team_ix[tm]] = {"pepa": r1(g.epa.mean(), 3), "repa": r1(r_.epa.mean(), 3),
                            "pexp": r1(100 * (att.yards_gained >= 20).mean()), "rexp": r1(100 * (r_.yards_gained >= 10).mean()),
                            "sackr": r1(100 * g.sack.mean()), "adot": r1(att.air_yards.mean()), "yac": r1(att.yards_after_catch.mean()),
                            "deep": r1(100 * (att[att.air_yards >= 20].complete_pass.mean()) if (att.air_yards >= 20).any() else None),
                            "mid": r1(att[att.pass_location == "middle"].epa.mean(), 3), "out": r1(att[att.pass_location != "middle"].epa.mean(), 3)}
    if pfr_pass is not None:
        pp = pfr_pass[pfr_pass.game_type == "REG"].copy()
        pp["opponent"] = pp.opponent.replace(alias)
        dbs = pa.groupby("defteam").size()
        for tm, g in pp.groupby("opponent"):
            if tm in team_ix and team_ix[tm] in dfn and dbs.get(tm):
                dfn[team_ix[tm]]["press"] = r1(100 * g.times_pressured.sum() / dbs[tm])
                dfn[team_ix[tm]]["blitz"] = r1(100 * g.times_blitzed.sum() / dbs[tm])
    keys = {"pepa": 0, "repa": 0, "pexp": 0, "rexp": 0, "sackr": 1, "press": 1, "blitz": 1, "deep": 0, "mid": 0, "out": 0, "yac": 0}
    for k, low_hurts_offense in keys.items():  # rank 1 = best for the offense (allows the most / pressures the least)
        vals = sorted(((v.get(k), t) for t, v in dfn.items() if v.get(k) is not None), reverse=not low_hurts_offense)
        for rk, (_, t) in enumerate(vals, 1):
            dfn[t].setdefault("rk", {})[k] = rk
    return {"season": season, "players": players, "defense": {str(k): v for k, v in dfn.items()}}


if __name__ == "__main__":
    for name, fn in (("nba", build_nba), ("nfl", build_nfl)):
        try:
            out = fn()
            with open(os.path.join(SITE, f"{name}_adv.json"), "w") as f:
                json.dump(out, f, separators=(",", ":"), allow_nan=False, default=lambda o: o.item() if hasattr(o, "item") else None)
            print(f"{name}: advanced stats for {len(out['players'])} players")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"{name}: advanced build failed: {e}")
