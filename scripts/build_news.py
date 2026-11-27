"""Build site/news.json: injury reports, team news headlines and logo URLs from ESPN's public site API.

Run after build_data.py: python scripts/build_news.py site
Never fails the deploy: on any error it writes what it has.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

SITE = sys.argv[1] if len(sys.argv) > 1 else "site"
API = "https://site.api.espn.com/apis/site/v2/sports"
PATHS = {"nba": "basketball/nba", "nfl": "football/nfl"}
SKIP_STATUS = {"active"}


def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sports-game-logs)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print("  failed:", url, e)
                return None
            time.sleep(2)


def norm(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s).strip()


def athlete_id(a):
    for link in a.get("links") or []:
        m = re.search(r"/id/(\d+)", link.get("href", ""))
        if m:
            return m.group(1)
    return str(a.get("id") or "")


def league(lg):
    with open(os.path.join(SITE, f"{lg}.json")) as f:
        stats = json.load(f)
    by_name = {t["n"].lower(): t["a"] for t in stats["teams"]}
    out = {"logo": {}, "inj": {}, "news": {}}

    # teams: ESPN ids + logos
    espn_id = {}
    d = get(f"{API}/{PATHS[lg]}/teams")
    try:
        for t in d["sports"][0]["leagues"][0]["teams"]:
            t = t["team"]
            abbr = by_name.get(t["displayName"].lower())
            if not abbr:
                continue
            espn_id[abbr] = t["id"]
            logos = t.get("logos") or []
            if logos:
                out["logo"][abbr] = logos[0]["href"]
    except Exception as e:  # noqa: BLE001
        print("  teams parse failed:", e)

    # injuries
    d = get(f"{API}/{PATHS[lg]}/injuries")
    try:
        for team in d.get("injuries", []):
            abbr = by_name.get((team.get("displayName") or "").lower())
            if not abbr:
                continue
            rows = []
            for inj in team.get("injuries", []):
                status = inj.get("status") or ""
                if status.lower() in SKIP_STATUS:
                    continue
                a = inj.get("athlete") or {}
                det = inj.get("details") or {}
                pos = (a.get("position") or {}).get("abbreviation", "")
                part = " ".join(x for x in (det.get("side") if det.get("side") not in (None, "Not Specified") else "",
                                            det.get("type") or "") if x).strip()
                rows.append({"n": a.get("displayName", ""), "k": norm(a.get("displayName", "")), "id": athlete_id(a),
                             "p": pos, "s": status, "w": part, "r": det.get("returnDate") or "",
                             "c": inj.get("shortComment") or "", "d": inj.get("date") or ""})
            order = {"out": 0, "injured reserve": 0, "doubtful": 1, "questionable": 2, "day-to-day": 3, "probable": 4}
            rows.sort(key=lambda r: (order.get(r["s"].lower(), 5), r["n"]))
            out["inj"][abbr] = rows
    except Exception as e:  # noqa: BLE001
        print("  injuries parse failed:", e)

    # news per team
    for abbr, tid in espn_id.items():
        d = get(f"{API}/{PATHS[lg]}/news?team={tid}&limit=20")
        if not d:
            continue
        items = []
        for art in d.get("articles", []):
            cats = art.get("categories") or []
            team_cats = [c for c in cats if c.get("type") == "team"]
            if len(team_cats) > 4:  # league-wide roundups tagged with every team
                continue
            athletes = []
            for c in cats:
                if c.get("type") == "athlete":
                    aid = c.get("athleteId") or (c.get("athlete") or {}).get("id")
                    if aid:
                        athletes.append(str(aid))
                    if c.get("description"):
                        athletes.append(norm(c["description"]))
            url = ((art.get("links") or {}).get("web") or {}).get("href", "")
            if not url.startswith("https://"):
                continue
            items.append({"h": art.get("headline", ""), "d": art.get("description", ""), "u": url,
                          "t": art.get("published", ""), "a": athletes, "ty": art.get("type", "")})
        items.sort(key=lambda x: x["t"], reverse=True)
        out["news"][abbr] = items[:12]
        time.sleep(0.2)
    print(f"{lg}: {len(out['logo'])} logos, {sum(len(v) for v in out['inj'].values())} injuries, "
          f"{sum(len(v) for v in out['news'].values())} articles")
    return out


if __name__ == "__main__":
    res = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    for lg in ("nba", "nfl"):
        try:
            res[lg] = league(lg)
        except Exception as e:  # noqa: BLE001
            print(lg, "failed:", e)
            res[lg] = {"logo": {}, "inj": {}, "news": {}}
    with open(os.path.join(SITE, "news.json"), "w") as f:
        json.dump(res, f, separators=(",", ":"))
