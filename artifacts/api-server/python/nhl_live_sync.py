#!/usr/bin/env python3
"""
Live ESPN NHL Score (Regulation / OT / SO / Shutout) + Optional Dedicated Google Sheets Sync
for Standalone NHL-FUSION-SIGNAL v82 (DEG1 = 88).
Uses NHL_FUSION_INPUT_SHEET_ID / NHL_FUSION_CALC_SHEET_ID from .env with safe local JSON fallback
so live NBA sheets are NEVER touched.
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fusion_roster_sync import recompute_all_fusion_modes, recompute_summary
from nhl_teams import NHL_DEG1, norm_team

INPUT_SHEET_ID = os.environ.get("NHL_FUSION_INPUT_SHEET_ID", "").strip()
CALC_SHEET_ID = os.environ.get("NHL_FUSION_CALC_SHEET_ID", "").strip()


def fetch_espn_nhl_date(d_iso: str):
    ds = d_iso.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={ds}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=12).read().decode("utf-8"))
    finals = {}
    for ev in data.get("events", []):
        st_type = ev.get("status", {}).get("type", {}) or {}
        if not st_type.get("completed"):
            continue
        short_det = str(st_type.get("shortDetail") or st_type.get("detail") or "")
        ot_tag = "SO" if "SO" in short_det else ("OT" if "OT" in short_det else "")
        comps = ev.get("competitions", [{}])[0].get("competitors", [])
        hc = next((c for c in comps if c.get("homeAway") == "home"), None)
        ac = next((c for c in comps if c.get("homeAway") == "away"), None)
        if not hc or not ac:
            continue
        h = norm_team(hc.get("team", {}).get("abbreviation") or hc.get("team", {}).get("displayName", ""))
        a = norm_team(ac.get("team", {}).get("abbreviation") or ac.get("team", {}).get("displayName", ""))
        try:
            hp = int(hc.get("score", 0) or 0)
            ap = int(ac.get("score", 0) or 0)
        except Exception:
            continue
        if hp == ap:
            if hc.get("winner"):
                hp += 1
            elif ac.get("winner"):
                ap += 1
        if hp >= 0 and ap >= 0 and (hp > 0 or ap > 0) and hp != ap:
            finals[(h, a)] = (hp, ap, ot_tag)
    return finals


def sync_fusion_sheets(games, summary, target_iso: str) -> bool:
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or not INPUT_SHEET_ID:
        return False
    try:
        from _lib.sheets import open_sheet
        sh_in = open_sheet(INPUT_SHEET_ID)
        ws1 = sh_in.sheet1
        today_games = [g for g in games if g["d"] == target_iso]
        if today_games:
            rows = [[
                "DATE", "WEEKDAY", "DEG1_FIXED", "HOME_TEAM", "AWAY_TEAM",
                "ARENA", "PUCKDROP_LOCAL", "FUSION_TIER", "FUSION_PICK",
                "HOME_1XXX_SUM", "AWAY_1XXX_SUM", "GEO_1XXX_WIN",
                "HOME_ALL8_SUM", "AWAY_ALL8_SUM", "EARTH_LOCK_OK", "NEG_ANCHOR_OK", "POS_INV_WIN", "SAFE_DL_WIN",
            ]]
            for g in today_games:
                fm = g.get("fusion_meta") or {}
                g1 = fm.get("geo1xxx") or {}
                gd = g1.get("guards") or {}
                pi = g1.get("pos_inv") or {}
                m12 = (fm.get("modes") or {}).get("tri_gf_ultralock") or {}
                m9 = (fm.get("modes") or {}).get("pos_inv_lock") or {}
                rows.append([
                    g["d"], g["day"], NHL_DEG1, g["h"], g["a"],
                    g.get("venue", ""), "19:30:00", fm.get("tier_fa", ""),
                    m12.get("pick") or m9.get("pick") or g.get("sys_win", ""),
                    g1.get("h_sum", 0.0), g1.get("a_sum", 0.0), g1.get("win", ""),
                    g1.get("h_all", 0.0), g1.get("a_all", 0.0),
                    "PASS" if gd.get("earth_ok") else "BLOCKED_EARTH",
                    "PASS" if gd.get("neg_anchor_ok") else ("POS_INV_TRAP" if gd.get("pos_inv_trap") else "NO_NEG_ANCHOR"),
                    pi.get("win", ""),
                    g1.get("safe_dl_win", ""),
                ])
            ws1.clear()
            ws1.update(values=rows, range_name="A1", value_input_option="RAW")
        if CALC_SHEET_ID and summary:
            sh_calc = open_sheet(CALC_SHEET_ID)
            ws_c = sh_calc.sheet1
            c_rows = [["MODE_KEY", "LABEL", "HOLDOUT_2527", "S2526", "S2627", "LAST50", "EDGE"]]
            for mk, st in summary.items():
                h_o = st.get("holdout_2527", {})
                s25 = st.get("s2526", {})
                s26 = st.get("s2627", {})
                l50 = st.get("last50", {})
                c_rows.append([
                    mk, st.get("label", ""),
                    f"{h_o.get('pct', 0)}% ({h_o.get('w', 0)}/{h_o.get('n', 0)})",
                    f"{s25.get('pct', 0)}% ({s25.get('w', 0)}/{s25.get('n', 0)})",
                    f"{s26.get('pct', 0)}% ({s26.get('w', 0)}/{s26.get('n', 0)})",
                    f"{l50.get('pct', 0)}% ({l50.get('w', 0)}/{l50.get('n', 0)})",
                    f"{h_o.get('edge', 0):+.1f}pp",
                ])
            ws_c.clear()
            ws_c.update(values=c_rows, range_name="A1", value_input_option="RAW")
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="")
    ap.add_argument("--end-date", default="")
    ap.add_argument("--target-date", default="")
    args = ap.parse_args()

    pub_dir = os.path.abspath(os.path.join(HERE, "../../calc-dashboard/public"))
    m_path = os.path.join(pub_dir, "fusion_nhl_master.json")
    doc = json.load(open(m_path, "r", encoding="utf-8"))
    games = doc["games"]

    today_utc = datetime.now(timezone.utc).date()
    max_check_iso = (today_utc + timedelta(days=1)).isoformat()
    min_recent_iso = (today_utc - timedelta(days=5)).isoformat()

    dates_to_check = set()
    for g in games:
        d_iso = g["d"]
        if d_iso <= max_check_iso and (not g.get("done") or g.get("aw") in (None, "", "PENDING") or d_iso >= min_recent_iso):
            if d_iso >= "2026-10-04":
                dates_to_check.add(d_iso)
    if args.target_date and len(args.target_date) == 10 and args.target_date <= max_check_iso:
        dates_to_check.add(args.target_date)
    if args.start_date and args.end_date:
        for g in games:
            if args.start_date <= g["d"] <= args.end_date:
                dates_to_check.add(g["d"])

    sorted_dates = sorted(dates_to_check)[-25:]
    updated_scores = 0
    all_finals_by_date = {}

    for d_iso in sorted_dates:
        try:
            finals = fetch_espn_nhl_date(d_iso)
        except Exception:
            continue
        if not finals:
            continue
        all_finals_by_date[d_iso] = finals
        for g in games:
            if g["d"] != d_iso:
                continue
            h_norm, a_norm = norm_team(g["h"]), norm_team(g["a"])
            if (h_norm, a_norm) not in finals:
                continue
            hp, ap_pts, ot_tag = finals[(h_norm, a_norm)]
            aw = h_norm if hp > ap_pts else a_norm
            new_sc = f"{hp}-{ap_pts} ({ot_tag})" if ot_tag else f"{hp}-{ap_pts}"
            was_done = bool(g.get("done") and g.get("hp") == hp and g.get("ap") == ap_pts and norm_team(g.get("aw")) == aw)
            g["hp"], g["ap"] = hp, ap_pts
            g["sc"] = new_sc
            if ot_tag:
                g["ot"] = ot_tag
            g["aw"] = aw
            g["done"] = True
            g["hw"] = bool(hp > ap_pts)
            recompute_all_fusion_modes(g)
            if not was_done:
                updated_scores += 1

    if updated_scores > 0 or "summary" not in doc:
        doc["summary"] = recompute_summary(games)
        doc["fusion_modes_summary"] = doc["summary"]

    if updated_scores > 0:
        tmp_m = m_path + ".tmp"
        json.dump(doc, open(tmp_m, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_m, m_path)

        fast_path = os.path.join(pub_dir, "fusion_nhl_fast.json")
        fast_games = [g for g in games if "2026-10-01" <= g["d"] <= "2027-01-15"]
        tmp_f = fast_path + ".tmp"
        json.dump({"games": fast_games, "summary": doc["summary"], "fusion_modes_summary": doc["summary"]}, open(tmp_f, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_f, fast_path)

        sum_path = os.path.join(pub_dir, "fusion_modes_summary.json")
        tmp_s = sum_path + ".tmp"
        json.dump(doc["summary"], open(tmp_s, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp_s, sum_path)

        pred_path = os.path.join(pub_dir, "nhl_predictions_2024_2027.json")
        if os.path.exists(pred_path) and all_finals_by_date:
            try:
                p_doc = json.load(open(pred_path, "r", encoding="utf-8"))
                for pg in p_doc.get("games", []):
                    f_d = all_finals_by_date.get(pg["d"])
                    if not f_d:
                        continue
                    hn, an = norm_team(pg["h"]), norm_team(pg["a"])
                    if (hn, an) in f_d:
                        hp, ap_pts, ot_tag = f_d[(hn, an)]
                        aw = pg["h"] if hp > ap_pts else pg["a"]
                        pg["hp"], pg["ap"] = hp, ap_pts
                        pg["sc"] = f"{hp}-{ap_pts} ({ot_tag})" if ot_tag else f"{hp}-{ap_pts}"
                        pg["aw"] = aw
                        pg["done"] = True
                        pg["hw"] = bool(hp > ap_pts)
                        pg["st"] = "WIN" if norm_team(pg.get("pw")) == norm_team(aw) else "LOSS"
                        pg["fst"] = "WIN" if norm_team(pg.get("fpw")) == norm_team(aw) else "LOSS"
                tmp_p = pred_path + ".tmp"
                json.dump(p_doc, open(tmp_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp_p, pred_path)
            except Exception:
                pass

    sheet_synced = sync_fusion_sheets(games, doc.get("summary"), args.target_date or today_utc.isoformat())

    done_auth = [g for g in games if g.get("done") and (g.get("fusion_meta") or {}).get("in_auth_overlap")]
    flagship_mk = "nhl_ice_ultralock" if any("nhl_ice_ultralock" in ((g.get("fusion_meta") or {}).get("modes") or {}) for g in done_auth[:5]) else "tri_gf_ultralock"
    oos = [g for g in done_auth if (g.get("fusion_meta") or {}).get("modes", {}).get(flagship_mk, {}).get("sig")]
    oos_w = sum(1 for g in oos if norm_team(g["fusion_meta"]["modes"][flagship_mk]["pick"]) == norm_team(g["aw"]))
    s26 = [g for g in oos if g.get("s") == "2026-27"]
    s26_w = sum(1 for g in s26 if norm_team(g["fusion_meta"]["modes"][flagship_mk]["pick"]) == norm_team(g["aw"]))

    payload = {
        "ok": True,
        "updatedScores": updated_scores,
        "checkedDates": sorted_dates,
        "sheetSynced": sheet_synced,
        "totalDone": len(done_auth),
        "oosF1": {"w": oos_w, "n": len(oos), "pct": round(100.0 * oos_w / max(1, len(oos)), 1)},
        "s2627": {"w": s26_w, "n": len(s26), "pct": round(100.0 * s26_w / max(1, len(s26)), 1)},
        "rowsWritten": updated_scores,
        "message": f"ESPN NHL Sync OK (updated {updated_scores} scores across {len(sorted_dates)} dates; 2026-27: {s26_w}/{len(s26)} = {round(100.0 * s26_w / max(1, len(s26)), 1)}%)",
    }
    print("__NHL_SYNC__ " + json.dumps(payload, ensure_ascii=False))
    print("__NBA_SYNC__ " + json.dumps(payload, ensure_ascii=False))
    print("__RESULT__ " + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
