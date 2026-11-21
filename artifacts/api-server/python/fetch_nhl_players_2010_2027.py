#!/usr/bin/env python3
"""
Fetch complete NHL player rosters, jersey names, jersey numbers, injury status (OUT / IR),
seasonal TOI/games (2009-10 through 2026-27), and 2026-27 game-by-game NHL boxscores (with OT/SO).
"""
import datetime
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from nhl_teams import ESPN_ABBR_TO_CANON, TEAM_TO_CODE, clean_ascii, norm_team

t0 = time.time()

NHL_BLOCKED_STATUSES = {
    "out", "ir", "ir-lt", "ir-nr", "ltir",
    "injured reserve", "suspension", "suspended",
}


def is_nhl_blocked_status(st: str, abbr: str = "") -> bool:
    s = str(st or "").strip().lower()
    a = str(abbr or "").strip().lower()
    if s in NHL_BLOCKED_STATUSES or a in {"o", "out", "ir", "ir-lt", "ir-nr", "susp"}:
        return True
    if "injured reserve" in s or s.startswith("ir"):
        return True
    return False


def parse_toi_minutes(raw_val) -> float:
    s = str(raw_val or "").strip()
    if not s:
        return 0.0
    if ":" in s:
        parts = s.split(":")
        try:
            mm = float(parts[0])
            ss = float(parts[1]) if len(parts) > 1 else 0.0
            return round(mm + ss / 60.0, 2)
        except Exception:
            return 0.0
    try:
        return round(float(s), 2)
    except Exception:
        return 0.0


def fetch_json(url: str, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=14).read().decode("utf-8")
            return json.loads(raw)
        except Exception:
            if attempt == retries:
                return None
            time.sleep(0.25 * (attempt + 1))
    return None


def main():
    # 1. Fetch all 32 live NHL rosters + league-wide injury report
    teams_meta = fetch_json("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams")
    espn_teams = [t["team"] for t in (teams_meta or {}).get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])]
    print(f"[1/5] Fetching {len(espn_teams)} live NHL rosters + injuries...")

    inj_all = fetch_json("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries") or {}
    inj_by_pid = {}
    inj_by_team_name = defaultdict(dict)
    for tblk in inj_all.get("injuries", []):
        tn = norm_team(tblk.get("displayName", ""))
        for item in tblk.get("injuries", []):
            st = str(item.get("status", "")).strip()
            t_ab = str((item.get("type") or {}).get("abbreviation", "")).strip()
            det = str((item.get("details") or {}).get("type", "")).strip()
            a_obj = item.get("athlete") or {}
            pid = str(a_obj.get("id", ""))
            fn = clean_ascii(a_obj.get("displayName") or a_obj.get("fullName") or "")
            eff_st = "IR" if ("injured reserve" in st.lower() or t_ab.upper().startswith("IR")) else st
            if pid:
                inj_by_pid[pid] = (eff_st, det)
            if fn and tn:
                inj_by_team_name[tn][fn.lower()] = (eff_st, det)

    live_rosters = {}
    player_master = {}

    def fetch_one_roster(tm_obj):
        tid = tm_obj["id"]
        abbr = str(tm_obj.get("abbreviation", "")).upper()
        canon_name, canon_code = ESPN_ABBR_TO_CANON.get(abbr, (norm_team(tm_obj.get("displayName", "")), abbr))
        d = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{tid}/roster")
        out = []
        raw_groups = (d or {}).get("athletes", [])
        flat_athletes = []
        for grp in raw_groups:
            if isinstance(grp, dict) and "items" in grp:
                flat_athletes.extend(grp.get("items") or [])
            elif isinstance(grp, dict):
                flat_athletes.append(grp)
        for a in flat_athletes:
            pid = str(a.get("id", ""))
            if not pid:
                continue
            full_name = clean_ascii(a.get("fullName") or a.get("displayName") or "")
            last_name = clean_ascii(a.get("lastName") or "")
            if not last_name and full_name:
                last_name = full_name.split()[-1]
            jersey_str = str(a.get("jersey") or "").strip()
            pos = str((a.get("position") or {}).get("abbreviation", ""))
            injs = a.get("injuries") or []
            inj_status = str(injs[0].get("status", "Healthy")) if injs else "Healthy"
            inj_detail = str((injs[0].get("details") or {}).get("type", "")) if injs else ""
            if pid in inj_by_pid:
                inj_status, inj_detail = inj_by_pid[pid]
            elif full_name.lower() in inj_by_team_name.get(canon_name, {}):
                inj_status, inj_detail = inj_by_team_name[canon_name][full_name.lower()]
            rec = {
                "pid": pid,
                "full_name": full_name,
                "jersey_name": last_name,
                "jersey": jersey_str,
                "pos": pos,
                "team": canon_name,
                "team_code": canon_code,
                "status": inj_status,
                "injury_detail": inj_detail,
            }
            out.append(rec)
        return canon_name, out

    with ThreadPoolExecutor(max_workers=16) as ex:
        for cname, plist in ex.map(fetch_one_roster, espn_teams):
            live_rosters[cname] = plist
            for p in plist:
                player_master[p["pid"]] = p.copy()

    print(f"  Live NHL rosters loaded: {len(live_rosters)} teams, {len(player_master)} active players ({time.time()-t0:.1f}s)")

    # 2. Fetch seasonal NHL athlete stats 2009-10..2026-27 (seasons 2010..2027)
    print("[2/5] Fetching seasonal NHL player TOI stats 2009-10..2026-27 (seasons 2010..2027)...")

    def season_label_from_espn_yr(yr: int) -> str:
        return f"{yr - 1}-{str(yr)[-2:]}"

    def fetch_season_stats(yr: int):
        s_lbl = season_label_from_espn_yr(yr)
        base_u = (
            "https://site.web.api.espn.com/apis/common/v3/sports/hockey/nhl/statistics/byathlete"
            f"?region=us&lang=en&contentorigin=espn&isqualified=false&limit=100&season={yr}&seasontype=2"
        )
        d1 = fetch_json(base_u + "&page=1")
        if not d1:
            return s_lbl, []
        pages = int((d1.get("pagination") or {}).get("pages", 1))
        all_aths = list(d1.get("athletes") or [])
        if pages > 1:
            with ThreadPoolExecutor(max_workers=6) as pex:
                for dp in pex.map(lambda pg: fetch_json(base_u + f"&page={pg}"), range(2, pages + 1)):
                    if dp and dp.get("athletes"):
                        all_aths.extend(dp["athletes"])
        parsed = []
        for item in all_aths:
            ath = item.get("athlete") or {}
            pid = str(ath.get("id", ""))
            if not pid:
                continue
            full_name = clean_ascii(ath.get("displayName") or ath.get("fullName") or "")
            last_name = clean_ascii(ath.get("lastName") or "")
            if not last_name and full_name:
                last_name = full_name.split()[-1]
            pos = str((ath.get("position") or {}).get("abbreviation", ""))
            gp, toi_pg, tot_min, pts = 0, 0.0, 0.0, 0.0
            for cat in (item.get("categories") or []):
                vals = cat.get("values") or []
                if cat.get("name") == "general" and len(vals) >= 8:
                    gp = int(round(float(vals[0] or 0)))
                    # ESPN NHL returns timeOnIcePerGame (vals[2]) and timeOnIce (vals[7]) in SECONDS
                    raw_pg = float(vals[2] or 0.0)
                    raw_tot = float(vals[7] or 0.0)
                    toi_pg = round(raw_pg / 60.0, 2) if raw_pg > 90 else round(raw_pg, 2)
                    tot_min = round(raw_tot / 60.0, 1) if raw_tot > 120 else round(raw_tot, 1)
                elif cat.get("name") == "offensive" and len(vals) >= 3:
                    pts = round(float(vals[2] or 0.0), 2)
            teams_arr = ath.get("teams") or []
            t_codes = []
            for t_obj in teams_arr:
                ab = str(t_obj.get("abbreviation") or "").upper()
                if ab in ESPN_ABBR_TO_CANON:
                    t_codes.append(ESPN_ABBR_TO_CANON[ab])
                else:
                    dn = norm_team(t_obj.get("displayName") or "")
                    if dn in TEAM_TO_CODE:
                        t_codes.append((dn, TEAM_TO_CODE[dn]))
            if not t_codes:
                ab = str(ath.get("teamShortName") or "").upper()
                if ab in ESPN_ABBR_TO_CANON:
                    t_codes.append(ESPN_ABBR_TO_CANON[ab])
            for cname, ccode in t_codes:
                parsed.append({
                    "pid": pid,
                    "season": s_lbl,
                    "team": cname,
                    "team_code": ccode,
                    "full_name": full_name,
                    "jersey_name": last_name,
                    "pos": pos,
                    "gp": gp,
                    "mpg": toi_pg,
                    "tot_min": round(tot_min / max(1, len(t_codes)), 1),
                    "ppg": round(pts / max(1, gp), 2),
                })
        return s_lbl, parsed

    season_team_players = defaultdict(list)
    all_season_rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for s_lbl, rows in ex.map(fetch_season_stats, range(2010, 2028)):
            all_season_rows.extend(rows)
            for r in rows:
                season_team_players[(r["season"], r["team"])].append(r)

    # Sort each (season, team): keep top skaters + top goalies by tot_min so every team has >=12 skaters + 1-2 goalies
    need_jersey_pids = set()
    cleaned_stp = {}
    for key, lst in season_team_players.items():
        # Deduplicate by pid within (season, team)
        by_pid = {}
        for r in lst:
            if r["pid"] not in by_pid or r["tot_min"] > by_pid[r["pid"]]["tot_min"]:
                by_pid[r["pid"]] = r
        uniq = list(by_pid.values())
        skaters = sorted([x for x in uniq if x["pos"] != "G"], key=lambda x: (x["tot_min"], x["mpg"], x["ppg"]), reverse=True)
        goalies = sorted([x for x in uniq if x["pos"] == "G"], key=lambda x: (x["tot_min"], x["gp"], x["mpg"]), reverse=True)
        # Combine top 1 goalie + top 13 skaters + #2 goalie -> sorted cleanly for Top-8 & Top-12 selection
        top_rot = []
        if goalies:
            top_rot.append(goalies[0])
        top_rot.extend(skaters[:13])
        if len(goalies) >= 2:
            top_rot.append(goalies[1])
        cleaned_stp[key] = top_rot
        for r in top_rot[:14]:
            pid = r["pid"]
            if pid not in player_master:
                player_master[pid] = {
                    "pid": pid,
                    "full_name": r["full_name"],
                    "jersey_name": r["jersey_name"],
                    "jersey": "",
                    "pos": r["pos"],
                    "team": r["team"],
                    "team_code": r["team_code"],
                    "status": "Historical",
                    "injury_detail": "",
                }
            if not player_master[pid].get("jersey"):
                need_jersey_pids.add(pid)

    print(f"  Seasonal rows: {len(all_season_rows)} across {len(cleaned_stp)} team-seasons. Missing jersey PIDs: {len(need_jersey_pids)} ({time.time()-t0:.1f}s)")

    # 3. Fetch jersey numbers for historical rotation players
    print(f"[3/5] Fetching jersey numbers for {len(need_jersey_pids)} historical NHL rotation players...")

    def fetch_ath_jersey(pid: str):
        d = fetch_json(f"https://site.web.api.espn.com/apis/common/v3/sports/hockey/nhl/athletes/{pid}", retries=1)
        ath = (d or {}).get("athlete") or {}
        j = str(ath.get("jersey") or "").strip()
        fn = clean_ascii(ath.get("fullName") or ath.get("displayName") or "")
        ln = clean_ascii(ath.get("lastName") or "")
        pos = str((ath.get("position") or {}).get("abbreviation", ""))
        return pid, j, fn, ln, pos

    with ThreadPoolExecutor(max_workers=32) as ex:
        for pid, j, fn, ln, pos in ex.map(fetch_ath_jersey, sorted(need_jersey_pids)):
            if j:
                player_master[pid]["jersey"] = j
            if fn and len(fn) > len(player_master[pid]["full_name"]):
                player_master[pid]["full_name"] = fn
            if ln and not player_master[pid]["jersey_name"]:
                player_master[pid]["jersey_name"] = ln
            if pos and not player_master[pid].get("pos"):
                player_master[pid]["pos"] = pos

    missing_j = sum(1 for pid in need_jersey_pids if not player_master[pid].get("jersey"))
    print(f"  Historical NHL jerseys resolved! Remaining without jersey: {missing_j}/{len(need_jersey_pids)} ({time.time()-t0:.1f}s)")

    # 4. Fetch 2026-27 NHL live scoreboards + boxscores (2026-10-04 through 2026-11-22)
    print("[4/5] Fetching 2026-27 NHL scoreboards (with OT/SO) & game boxscores...")
    start_d = datetime.date(2026, 10, 4)
    end_d = datetime.date(2026, 11, 22)
    dates_2627 = [(start_d + datetime.timedelta(days=i)) for i in range((end_d - start_d).days + 1)]

    def fetch_sb_day(dt_obj: datetime.date):
        ymd = dt_obj.strftime("%Y%m%d")
        d_iso = dt_obj.isoformat()
        d = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={ymd}")
        evts = []
        for ev in (d or {}).get("events", []):
            eid = str(ev.get("id", ""))
            st_type = (ev.get("status") or {}).get("type") or {}
            completed = bool(st_type.get("completed"))
            short_det = str(st_type.get("shortDetail") or st_type.get("detail") or "")
            ot_tag = "SO" if "SO" in short_det else ("OT" if "OT" in short_det else "")
            comps = (ev.get("competitions") or [{}])[0]
            competitors = comps.get("competitors") or []
            hc = next((c for c in competitors if c.get("homeAway") == "home"), None)
            ac = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not hc or not ac:
                continue
            hab = str((hc.get("team") or {}).get("abbreviation", "")).upper()
            aab = str((ac.get("team") or {}).get("abbreviation", "")).upper()
            h_name = ESPN_ABBR_TO_CANON.get(hab, (norm_team((hc.get("team") or {}).get("displayName", "")), hab))[0]
            a_name = ESPN_ABBR_TO_CANON.get(aab, (norm_team((ac.get("team") or {}).get("displayName", "")), aab))[0]
            hp = int(hc.get("score") or 0) if completed else 0
            ap = int(ac.get("score") or 0) if completed else 0
            if completed and hp == ap:
                if hc.get("winner"):
                    hp += 1
                elif ac.get("winner"):
                    ap += 1
            evts.append({
                "eid": eid, "d": d_iso, "completed": completed,
                "h": h_name, "a": a_name, "hp": hp, "ap": ap, "ot": ot_tag,
            })
        return evts

    events_2627 = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for ev_list in ex.map(fetch_sb_day, dates_2627):
            events_2627.extend(ev_list)

    completed_evts = [e for e in events_2627 if e["completed"] and e["hp"] != e["ap"]]
    print(f"  Found {len(events_2627)} NHL events in 2026-10-04..11-22 ({len(completed_evts)} completed). Fetching boxscores...")

    def fetch_box(ev):
        eid = ev["eid"]
        d = fetch_json(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={eid}")
        bx_teams = ((d or {}).get("boxscore") or {}).get("players") or []
        team_players = {}
        for bt in bx_teams:
            ab = str((bt.get("team") or {}).get("abbreviation", "")).upper()
            tname = ESPN_ABBR_TO_CANON.get(ab, (norm_team((bt.get("team") or {}).get("displayName", "")), ab))[0]
            by_pid = {}
            for sg in (bt.get("statistics") or []):
                sg_name = str(sg.get("name") or "").lower()
                keys = sg.get("keys") or []
                labels = sg.get("labels") or []
                if "timeOnIce" in keys:
                    toi_idx = keys.index("timeOnIce")
                elif "TOI" in labels:
                    toi_idx = labels.index("TOI")
                else:
                    continue
                g_idx = keys.index("goals") if "goals" in keys else -1
                a_idx = keys.index("assists") if "assists" in keys else -1
                for row in (sg.get("athletes") or []):
                    if row.get("didNotPlay"):
                        continue
                    ath = row.get("athlete") or {}
                    pid = str(ath.get("id", ""))
                    st_vals = row.get("stats") or []
                    if not pid or toi_idx >= len(st_vals):
                        continue
                    toi_min = parse_toi_minutes(st_vals[toi_idx])
                    if toi_min <= 0:
                        continue
                    pts = 0
                    try:
                        if g_idx >= 0 and g_idx < len(st_vals):
                            pts += int(st_vals[g_idx])
                        if a_idx >= 0 and a_idx < len(st_vals):
                            pts += int(st_vals[a_idx])
                    except Exception:
                        pts = 0
                    fn = clean_ascii(ath.get("displayName") or ath.get("fullName") or "")
                    ln = clean_ascii(ath.get("lastName") or "")
                    if not ln and fn:
                        ln = fn.split()[-1]
                    j = str(ath.get("jersey") or "").strip()
                    pos = str((ath.get("position") or {}).get("abbreviation", ""))
                    if not pos and sg_name == "goalies":
                        pos = "G"
                    if pid not in player_master:
                        player_master[pid] = {
                            "pid": pid, "full_name": fn, "jersey_name": ln, "jersey": j,
                            "pos": pos, "team": tname, "team_code": TEAM_TO_CODE.get(tname, ab),
                            "status": "Healthy", "injury_detail": "",
                        }
                    else:
                        if j and not player_master[pid].get("jersey"):
                            player_master[pid]["jersey"] = j
                        if pos and not player_master[pid].get("pos"):
                            player_master[pid]["pos"] = pos
                    prev = by_pid.get(pid)
                    if prev is None or toi_min > prev["min"]:
                        by_pid[pid] = {
                            "pid": pid,
                            "pos": pos or player_master[pid].get("pos", ""),
                            "starter": bool(row.get("starter")) or (pos == "G" and toi_min >= 30.0) or (toi_min >= 18.0),
                            "min": toi_min,
                            "pts": pts,
                            "jersey": j or player_master[pid].get("jersey", ""),
                        }
            plist = sorted(by_pid.values(), key=lambda x: (x["pos"] == "G" and x["min"] >= 30.0, x["min"]), reverse=True)
            team_players[tname] = plist
        return eid, {"d": ev["d"], "h": ev["h"], "a": ev["a"], "hp": ev["hp"], "ap": ev["ap"], "ot": ev["ot"], "box": team_players}

    boxscores_2627 = {}
    with ThreadPoolExecutor(max_workers=24) as ex:
        for eid, bobj in ex.map(fetch_box, completed_evts):
            boxscores_2627[eid] = bobj

    serializable_stp = {}
    for (s_lbl, tname), lst in cleaned_stp.items():
        enriched = []
        for r in lst[:15]:
            pm = player_master.get(r["pid"], {})
            r2 = dict(r)
            r2["jersey"] = pm.get("jersey", "")
            r2["full_name"] = pm.get("full_name") or r["full_name"]
            r2["jersey_name"] = pm.get("jersey_name") or r["jersey_name"]
            r2["pos"] = pm.get("pos") or r["pos"]
            enriched.append(r2)
        serializable_stp[f"{s_lbl}||{tname}"] = enriched

    out_bundle = {
        "player_master": player_master,
        "live_rosters": live_rosters,
        "season_team_players": serializable_stp,
        "events_2627": events_2627,
        "boxscores_2627": boxscores_2627,
    }
    out_path = os.path.join(HERE, "nhl_players_2010_2027.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_bundle, f, ensure_ascii=False)
    print(f"  Saved nhl_players_2010_2027.json: {len(player_master)} NHL players, {len(boxscores_2627)} 2026-27 boxscores ({time.time()-t0:.1f}s)")

    # 5. Also snapshot live Kalshi KXNHLGAME markets for offline/mock fallback
    print("[5/5] Caching live Kalshi KXNHLGAME markets...")
    pub_dir = os.path.abspath(os.path.join(HERE, "../../calc-dashboard/public"))
    km = fetch_json("https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNHLGAME&status=open&limit=200") or {}
    kmap = {}
    for m in km.get("markets") or []:
        yes_ask = float(m.get("yes_ask_dollars") or ((m.get("yes_ask") or 0) / 100.0))
        yes_bid = float(m.get("yes_bid_dollars") or ((m.get("yes_bid") or 0) / 100.0))
        last_p = float(m.get("last_price_dollars") or ((m.get("last_price") or 0) / 100.0))
        kmap[m["ticker"]] = {
            "ticker": m["ticker"],
            "eventTicker": m.get("event_ticker", ""),
            "title": m.get("title", ""),
            "yesSubTitle": m.get("yes_sub_title", ""),
            "yesAsk": yes_ask,
            "yesBid": yes_bid,
            "lastPrice": last_p,
            "yesAskCents": round(yes_ask * 100),
            "yesBidCents": round(yes_bid * 100),
            "volume": m.get("volume_fp") or m.get("volume") or 0,
            "status": m.get("status", "open"),
        }
    os.makedirs(pub_dir, exist_ok=True)
    with open(os.path.join(pub_dir, "kalshi_nhl_markets.json"), "w", encoding="utf-8") as f:
        json.dump({"updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "markets": kmap}, f, ensure_ascii=False)
    print(f"DONE in {time.time()-t0:.1f}s! Cached {len(kmap)} open KXNHLGAME markets.")


if __name__ == "__main__":
    main()
