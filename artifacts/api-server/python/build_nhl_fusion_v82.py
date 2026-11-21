#!/usr/bin/env python3
"""
NHL-FUSION-SIGNAL v82 14-Mode Master Builder:
Directly combines:
  1) Team Engine (`nhl_predictions_2024_2027.json` • DEG1 = 88)
  2) Ready Player Engine Mode C (`player_nhl_preds_mode_c.json` & `player_nhl_hist_mode_c.json`
     from `moghimarash-create/NHL-PLAYER-SIGNAL` • DEG1 = 88, DEG2 = egem(Full_Name)%360, DEG3 = JerseyNoEff%360)
Computes all 14 Engine Modes (Modes 1–14, including Mode 12 default 3-number fusion super-lock + cold pole 0xxx
+ 2 safety locks v68, Mode 13 Smart Anti-NO-BET, and Mode 14 12-player + Team+Arena total element polarity v82)
with ZERO changes to the v82 mathematical formulas or decision rules.
"""
import datetime
import json
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PUB_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "calc-dashboard", "public"))
sys.path.insert(0, HERE)

import fusion_player_eval as pc
from nhl_teams import NHL_DEG1, TEAM_META_32, TEAM_TO_CODE, TEAM_TO_TZ, norm_team
from fusion_roster_sync import (
    build_nhl_ice_snapshots,
    compute_total_elem_12_block,
    geo_code_from_ef_str,
    is_blocked_nhl_status,
    make_ice_wtp_obj,
    recompute_all_fusion_modes,
    recompute_summary,
)

t0 = time.time()

print("[1/5] Loading Team Engine (nhl_predictions_2024_2027.json) & Ready Player Mode C (NHL-PLAYER-SIGNAL)...")
t_doc = json.load(open(os.path.join(PUB_DIR, "nhl_predictions_2024_2027.json"), "r", encoding="utf-8"))
t_games = t_doc["games"] if isinstance(t_doc, dict) else t_doc
pc_doc = json.load(open(os.path.join(PUB_DIR, "player_nhl_preds_mode_c.json"), "r", encoding="utf-8"))
pc_games = pc_doc["games"] if isinstance(pc_doc, dict) else pc_doc
p_hist_c = json.load(open(os.path.join(PUB_DIR, "player_nhl_hist_mode_c.json"), "r", encoding="utf-8"))

pb = json.load(open(os.path.join(HERE, "nhl_players_2010_2027.json"), "r", encoding="utf-8"))
player_master = pb["player_master"]
live_rosters = {norm_team(k): v for k, v in pb["live_rosters"].items()}
season_team_players = pb["season_team_players"]
boxscores_2627 = pb["boxscores_2627"]

print(
    f"  Loaded {len(t_games)} Team games, {len(pc_games)} Player Mode C games, "
    f"and {len(p_hist_c)} Player Mode C historical archive rows."
)

print("[2/5] Preparing canonical NHL-PLAYER-SIGNAL pre-game player metadata & boxscore index...")
p_static = {}
for pid, pm in player_master.items():
    fn = pc.clean_ascii(pm.get("full_name") or "")
    jn = pc.clean_ascii(pm.get("jersey_name") or (fn.split()[-1] if fn else ""))
    j_str = str(pm.get("jersey") or "").strip()
    deg2 = pc.egem(fn) % 360
    j_eff = pc.jersey_eff_num(j_str, zero_rule=True)
    deg3_c = j_eff % 360
    nam_fawe = tuple(pc.s4.word_element_fawe(fn))
    p_static[str(pid)] = {
        "pid": str(pid),
        "fn": fn,
        "jn": jn,
        "j_str": j_str if j_str != "" else "0",
        "j_eff": j_eff,
        "pos": pm.get("pos", ""),
        "status": pm.get("status", "Healthy"),
        "deg2": deg2,
        "deg3": deg3_c,
        "nam_fawe": nam_fawe,
    }

team_box_2627 = defaultdict(list)
for eid, bobj in boxscores_2627.items():
    d_b = bobj["d"]
    for tname, plist in bobj["box"].items():
        norm_plist = []
        for pr in plist:
            norm_plist.append({
                "pid": str(pr["pid"]),
                "min": float(pr.get("toi") if pr.get("toi") is not None else pr.get("min", 0.0)),
                "toi": float(pr.get("toi") if pr.get("toi") is not None else pr.get("min", 0.0)),
                "starter": bool(pr.get("starter", False)),
            })
        team_box_2627[norm_team(tname)].append((d_b, norm_plist))
for tname in team_box_2627:
    team_box_2627[tname].sort(key=lambda x: x[0])

live_roster_pids = {
    tname: {str(p["pid"]): p for p in plist}
    for tname, plist in live_rosters.items()
}

base_mpg_2526 = defaultdict(dict)
prior_2526_by_team = defaultdict(dict)
for k_stp, rows in season_team_players.items():
    if k_stp.startswith("2025-26||"):
        tm_n = norm_team(k_stp.split("||", 1)[1])
        for r in rows:
            toi_r = float(r.get("toi") or r.get("mpg") or 15.0)
            gp_r = int(r.get("gp") or 0)
            tot_r = float(r.get("tot_min") or 0.0)
            base_mpg_2526[tm_n][str(r["pid"])] = toi_r
            prior_2526_by_team[tm_n][str(r["pid"])] = (toi_r, gp_r, tot_r)


def get_pregame_lineup(tname, s_lbl, d_iso, is_pending=False, top_k=8):
    """
    Clean Zero-Lookahead NHL 1-Goalie + Skaters Selector:
      - Top-8  = AT MOST 1 active primary/starting Goalie (ranked by games started/played & total ice time)
               + Top 7 active Skaters (C/LW/RW/F/D) weighted/sorted by TOI.
      - Top-12 = AT MOST 1 active primary/starting Goalie + Top 11 active Skaters weighted/sorted by TOI.
    """
    cur_roster = live_roster_pids.get(tname, {})
    if s_lbl == "2026-27":
        prior_games = [plist for (db, plist) in team_box_2627.get(tname, []) if db < d_iso]
        p25 = prior_2526_by_team.get(tname, {})
        if prior_games:
            min_sums = defaultdict(float)
            gp_cnts = defaultdict(int)
            st_cnts = defaultdict(int)
            recent = prior_games[-10:]
            for plist in recent:
                for pr in plist:
                    pid_s = str(pr["pid"])
                    min_sums[pid_s] += float(pr.get("toi") or pr.get("min") or 0.0)
                    gp_cnts[pid_s] += 1
                    if pr.get("starter"):
                        st_cnts[pid_s] += 1
            goalie_cands = []
            skater_cands = []
            all_pids = set(min_sums.keys()) | (set(cur_roster.keys()) if is_pending else set())
            for pid in all_pids:
                if pid not in p_static:
                    continue
                if is_pending:
                    if cur_roster and pid not in cur_roster:
                        continue
                    st_lbl = str(cur_roster.get(pid, {}).get("status", "Healthy"))
                    if is_blocked_nhl_status(st_lbl):
                        continue
                g_c = gp_cnts.get(pid, 0)
                obs_m = (min_sums[pid] / g_c) if g_c > 0 else 0.0
                pos_s = p_static[pid].get("pos", "")
                is_g = pc.is_nhl_goalie(pos_s, obs_m)
                pr_toi, pr_gp, _ = p25.get(pid, (56.0 if is_g else 14.0, 0, 0.0))
                blend_toi = (g_c * obs_m + 2.0 * pr_toi) / (g_c + 2.0) if g_c > 0 else (pr_toi * 0.4)
                if is_g:
                    if g_c > 0 or (is_pending and pr_gp >= 10):
                        goalie_cands.append((pid, blend_toi, st_cnts.get(pid, 0), min_sums.get(pid, 0.0), pr_gp))
                else:
                    if blend_toi >= 6.0:
                        skater_cands.append((pid, blend_toi, min_sums.get(pid, 0.0), st_cnts.get(pid, 0)))
            picked = pc.select_nhl_1g_plus_skaters(goalie_cands, skater_cands, top_k=top_k)
            if len(picked) >= min(6, top_k):
                return picked

    raw_list = season_team_players.get(f"{s_lbl}||{tname}", [])
    if not raw_list:
        y0 = int(s_lbl[:4])
        raw_list = season_team_players.get(f"{y0-1}-{str(y0)[-2:]}||{tname}", [])
    if not raw_list and cur_roster:
        raw_list = [
            {"pid": pid, "toi": 56.0 if pc.is_nhl_goalie(p.get("pos")) else 16.0, "gp": 20, "tot_min": 300.0, "pos": p.get("pos", "")}
            for pid, p in cur_roster.items()
        ]

    goalie_cands = []
    skater_cands = []
    qual_skaters = [
        r for r in raw_list
        if not pc.is_nhl_goalie(r.get("pos"), r.get("toi", r.get("mpg", 0))) and int(r.get("gp", 0)) >= 15
    ]
    min_gp_req = 15 if len(qual_skaters) >= (top_k - 1) else 0

    for r in raw_list:
        pid = str(r["pid"])
        if pid not in p_static:
            continue
        if is_pending and cur_roster:
            if pid not in cur_roster:
                continue
            if is_blocked_nhl_status(cur_roster[pid].get("status", "")):
                continue
        toi_v = max(8.0, float(r.get("toi") or r.get("mpg") or 15.0))
        gp_v = int(r.get("gp") or 0)
        tot_m = float(r.get("tot_min") or (gp_v * toi_v))
        is_g = pc.is_nhl_goalie(p_static[pid].get("pos") or r.get("pos"), toi_v)
        if is_g:
            goalie_cands.append((pid, toi_v, gp_v, tot_m, gp_v))
        else:
            if gp_v >= min_gp_req:
                skater_cands.append((pid, toi_v, tot_m, gp_v))
    return pc.select_nhl_1g_plus_skaters(goalie_cands, skater_cands, top_k=top_k)


def build_player_cards_8(d_ctx, lineup, tbl):
    cards = []
    for pid, toi_val, is_st in lineup:
        ps = p_static[pid]
        d2, d3 = ps["deg2"], ps["deg3"]
        ep, ef, ed, md = pc.fast_eval_entity(d_ctx, NHL_DEG1, d2, d3, ps["nam_fawe"], tbl)
        pwr = round(
            (-md["qfin"][1]) * 1.5
            + (abs(md["qdec"][0]) + abs(md["qdec"][1])) * 0.08
            + (ed[0] + ed[1] - ed[2] - ed[3]) * 1.2,
            1,
        )
        ef_s = f"{ef[0]}-{ef[1]}-{ef[2]}-{ef[3]}"
        cards.append({
            "pid": pid,
            "fn": ps["fn"],
            "jn": ps["jn"],
            "no": ps["j_str"],
            "pos": ps["pos"],
            "st": is_st,
            "toi": toi_val,
            "mpg": toi_val,
            "d2": d2,
            "d3": d3,
            "ep": f"{ep[0]}-{ep[1]}-{ep[2]}-{ep[3]}",
            "ef": ef_s,
            "gf": geo_code_from_ef_str(ef_s),
            "qf": f"{pc.s4.fmt_hc(md['qfin'][0], False)}/{pc.s4.fmt_md(md['qfin'][1], False)}",
            "dec": md["decan_lbl"],
            "pwr": pwr,
        })
    return cards


def parse_votes(g):
    v = str(g.get("twVotes", "0H-0A"))
    try:
        hp_v, ap_v = v.replace("A", "").split("H-")
        return int(hp_v), int(ap_v)
    except Exception:
        return 0, 0


t_map = {(g["d"], norm_team(g["h"]), norm_team(g["a"])): g for g in t_games}

done_hist_all = []
sched_set_all = set()
ice_cut_pairs = set()
for r in p_hist_c:
    d_r, s_r, h_r, a_r, hp_r, ap_r = str(r[0]), str(r[2]), norm_team(r[3]), norm_team(r[4]), int(r[5]), int(r[6])
    sched_set_all.add((d_r, h_r))
    sched_set_all.add((d_r, a_r))
    done_hist_all.append({"d": d_r, "s": s_r, "h": h_r, "a": a_r, "hp": hp_r, "ap": ap_r, "mg": hp_r - ap_r})
done_hist_all.sort(key=lambda x: x["d"])
for gpc in pc_games:
    d_g = gpc["d"]
    h_g, a_g = norm_team(gpc["h"]), norm_team(gpc["a"])
    sched_set_all.add((d_g, h_g))
    sched_set_all.add((d_g, a_g))
    ice_cut_pairs.add((d_g, gpc["s"]))
all_ice_snaps = build_nhl_ice_snapshots(done_hist_all, ice_cut_pairs)

print("[3/5] Combining Team Engine + NHL-PLAYER-SIGNAL Mode C across all 4,136 games (16 Modes)...")
master_games = []
parity_verified_2627 = False

for gpc in pc_games:
    d_iso = gpc["d"]
    h = norm_team(gpc["h"])
    a = norm_team(gpc["a"])
    s_lbl = gpc["s"]
    is_pend = not bool(gpc.get("done"))

    gt = t_map.get((d_iso, h, a))
    in_auth = gt is not None
    if gt is None:
        raise RuntimeError(f"Missing Team prediction for {(d_iso, h, a)}")

    # Exact Team Engine signals from nhl_predictions_2024_2027.json
    tpk = norm_team(gt.get("sys_win") or gt.get("fpw") or gt.get("pw") or h)
    # Exact Player Engine Mode C signals from NHL-PLAYER-SIGNAL player_nhl_preds_mode_c.json
    ppk = norm_team(gpc.get("sys_win") or gpc.get("pw") or h)

    sgn_t = 1 if tpk == h else -1
    sgn_p = 1 if ppk == h else -1
    f30_t = int(gt.get("f30") if gt.get("f30") is not None else 0)
    f30_p = int(gpc.get("f30") if gpc.get("f30") is not None else 0)
    t_sig = bool(gt.get("f1_wtp"))
    p_sig = bool(gpc.get("f1_wtp"))
    t_vip = bool(gt.get("vip_idx3"))
    p_vip = bool(gpc.get("vip_idx3"))

    p_supports_t = (ppk == tpk) or (f30_p * sgn_t > 0)
    t_supports_p = (tpk == ppk) or (f30_t * sgn_p > 0)
    p_astro_t = (f30_p * sgn_t > 0)
    t_astro_p = (f30_t * sgn_p > 0)

    is_diamond = bool(t_sig and p_sig and tpk == ppk)
    is_vip_cross = bool((t_vip and p_supports_t and (not p_vip or tpk == ppk)) or (p_vip and t_supports_p and (not t_vip or tpk == ppk)))
    is_astro_lock = bool((t_sig and p_astro_t and (not p_sig or tpk == ppk)) or (p_sig and t_astro_p and (not t_sig or tpk == ppk)))
    is_dual_pillar = bool((t_sig and p_supports_t and (not p_sig or tpk == ppk)) or (p_sig and t_supports_p and (not t_sig or tpk == ppk)))
    is_vetoed = bool((t_sig or p_sig) and not is_dual_pillar)

    if is_diamond:
        final_pick, driver, tier_code, tier_fa = tpk, "BOTH", "DIAMOND", "سطح ۱: الماس (توافق هم‌زمان دو سیگنال)"
    elif is_vip_cross:
        final_pick = tpk if (t_vip and p_supports_t) else ppk
        driver = "TEAM" if final_pick == tpk else "PLAYER"
        tier_code, tier_fa = "GOLD_VIP", "سطح ۲: طلایی (VIP با تأیید متقابل)"
    elif is_dual_pillar:
        final_pick = tpk if (t_sig and p_supports_t) else ppk
        driver = "TEAM" if final_pick == tpk else "PLAYER"
        tier_code, tier_fa = "SILVER_CORE", "سطح ۳: نقره‌ای (تأیید دو-ستونی)"
    elif is_vetoed:
        final_pick = tpk if t_sig else ppk
        driver = "TEAM" if t_sig else "PLAYER"
        tier_code, tier_fa = "VETOED", "وتوی متقابل (مخالفت همزاد و نجوم موتور مکمل)"
    else:
        final_pick = tpk if abs(f30_t) >= abs(f30_p) else ppk
        driver = "TEAM" if final_pick == tpk else "PLAYER"
        tier_code, tier_fa = "NONE", "بدون سیگنال نهایی"

    pk_vip = tpk if (t_vip and p_supports_t) else (ppk if (p_vip and t_supports_p) else final_pick)
    pk_ast = tpk if (t_sig and p_astro_t) else (ppk if (p_sig and t_astro_p) else final_pick)
    pk_dp = tpk if (t_sig and p_supports_t) else (ppk if (p_sig and t_supports_p) else final_pick)
    pk_dia = tpk if is_diamond else final_pick

    d_ctx = pc.get_date_ctx(d_iso)
    tbl_u = d_ctx[8]

    g_out = dict(gpc)
    g_out["h"] = h
    g_out["a"] = a
    g_out["hc"] = TEAM_TO_CODE.get(h, gpc.get("hc", ""))
    g_out["ac"] = TEAM_TO_CODE.get(a, gpc.get("ac", ""))
    g_out["ice_wtp"] = make_ice_wtp_obj(all_ice_snaps[(d_iso, s_lbl)], h, a, d_iso, sched_set_all)

    # 8-player lineup (1 Primary Goalie + 7 Skaters by TOI)
    hp_list = [dict(p) for p in (gpc.get("h_players") or [])]
    ap_list = [dict(p) for p in (gpc.get("a_players") or [])]
    if hp_list and ap_list:
        if not parity_verified_2627:
            hl8_chk = get_pregame_lineup(h, s_lbl, d_iso, is_pend, top_k=8)
            re_chk = build_player_cards_8(d_ctx, hl8_chk, tbl_u)
            assert [x["pid"] for x in re_chk] == [str(x["pid"]) for x in hp_list], "Lineup selector parity mismatch!"
            assert [x["pwr"] for x in re_chk] == [x["pwr"] for x in hp_list], "Player pwr parity mismatch!"
            parity_verified_2627 = True
        for pl in hp_list:
            pl["gf"] = geo_code_from_ef_str(pl["ef"])
        for pl in ap_list:
            pl["gf"] = geo_code_from_ef_str(pl["ef"])
    else:
        hl8 = get_pregame_lineup(h, s_lbl, d_iso, is_pend, top_k=8)
        al8 = get_pregame_lineup(a, s_lbl, d_iso, is_pend, top_k=8)
        hp_list = build_player_cards_8(d_ctx, hl8, tbl_u)
        ap_list = build_player_cards_8(d_ctx, al8, tbl_u)

    g_out["h_players"] = hp_list
    g_out["a_players"] = ap_list

    # 12-player (1 Primary Goalie + 11 Skaters by TOI) + Team+Arena entity polarity block
    hl12 = get_pregame_lineup(h, s_lbl, d_iso, is_pend, top_k=12)
    al12 = get_pregame_lineup(a, s_lbl, d_iso, is_pend, top_k=12)
    t12_blk = compute_total_elem_12_block(
        d_ctx, tbl_u, h, a, hl12, al12, p_static, include_players=(d_iso >= "2026-10-01")
    )

    base_disp = gt if driver in ("TEAM", "BOTH") else gpc
    g_out["sys_win"] = pk_dp
    g_out["pw"] = pk_dp
    g_out["fpw"] = pk_dp if is_dual_pillar else ""
    g_out["twWin"] = pk_dp
    if is_diamond:
        thw, taw = parse_votes(gt)
        phw, paw = parse_votes(gpc)
        shw, saw = thw + phw, taw + paw
        g_out["twVotes"] = f"{shw}H-{saw}A"
        g_out["twPct"] = f"{round(100 * max(shw, saw) / max(1, shw + saw))}%"
    else:
        g_out["twVotes"] = base_disp.get("twVotes", gpc["twVotes"])
        g_out["twPct"] = base_disp.get("twPct", gpc["twPct"])

    g_out["idx3"] = base_disp.get("idx3") or gpc["idx3"]
    g_out["f30"] = int(f30_t + f30_p)
    g_out["vm6"] = int(f30_t + f30_p)
    g_out["f1"] = bool(is_dual_pillar or is_vetoed)
    g_out["f1_idx"] = is_dual_pillar
    g_out["f1_guard"] = is_dual_pillar
    g_out["f1_wtp"] = is_dual_pillar
    g_out["vip_idx3"] = is_vip_cross
    g_out["f1_union"] = is_dual_pillar
    if is_vetoed:
        g_out["trap_tag"] = "وتوی متقابل توسط " + ("موتور بازیکنان" if t_sig else "موتور تیم+استادیوم")
    elif is_dual_pillar:
        g_out["trap_tag"] = ""

    if g_out.get("done") and g_out.get("aw") and g_out.get("aw") != "PENDING":
        aw_n = norm_team(g_out["aw"])
        g_out["aw"] = aw_n
        g_out["st"] = "WIN" if pk_dp == aw_n else "LOSS"
        g_out["fst"] = g_out["st"] if is_dual_pillar else ""

    t_idx = gt.get("idx3") or {}
    p_idx = gpc.get("idx3") or {}
    g_out["fusion_meta"] = {
        "mode": "nhl_ice_ultralock",
        "tier": tier_code,
        "tier_fa": tier_fa,
        "driver": driver,
        "in_auth_overlap": in_auth,
        "vetoed": is_vetoed,
        "modes": {
            "dual_pillar": {"sig": is_dual_pillar, "vip": is_vip_cross, "pick": pk_dp},
            "vip_cross": {"sig": is_vip_cross, "vip": is_diamond, "pick": pk_vip},
            "astro_lock": {"sig": is_astro_lock, "vip": bool(is_astro_lock and is_vip_cross), "pick": pk_ast},
            "diamond": {"sig": is_diamond, "vip": is_diamond, "pick": pk_dia},
        },
        "team": {
            "pick": tpk,
            "votes": gt.get("twVotes", "—"),
            "pct": gt.get("twPct", "—"),
            "f30": f30_t,
            "ch": f"{t_idx.get('vh', 0)}H-{t_idx.get('va', 0)}A",
            "sig": t_sig,
            "vip": t_vip,
            "union": bool(gt.get("f1_union", t_sig)),
            "deg2": TEAM_META_32[h]["deg2"],
            "deg3": TEAM_META_32[h]["deg3"],
        },
        "player": {
            "pick": ppk,
            "votes": gpc.get("twVotes", "—"),
            "pct": gpc.get("twPct", "—"),
            "f30": f30_p,
            "ch": f"{p_idx.get('vh', 0)}H-{p_idx.get('va', 0)}A",
            "sig": p_sig,
            "vip": p_vip,
            "union": bool(gpc.get("f1_union", p_sig)),
        },
    }
    if t12_blk:
        g_out["fusion_meta"]["total_elem_12"] = t12_blk

    recompute_all_fusion_modes(g_out)
    master_games.append(g_out)

assert parity_verified_2627, "2026-27 parity check with NHL-PLAYER-SIGNAL did not run!"
print("  [OK] Verified 100% bit-for-bit player lineup & pwr parity with NHL-PLAYER-SIGNAL Mode C!")

print("[4/5] Computing 16-Mode out-of-sample & full-overlap fusion benchmarks...")
summary = recompute_summary(master_games)
for mk, st in summary.items():
    h2527 = st["holdout_2527"]
    s2627 = st["s2627"]
    l50 = st["last50"]
    all_o = st["all_overlap"]
    print(
        f"  {mk:18s} | All 24-27: {all_o['pct']:5.1f}% ({all_o['w']}/{all_o['n']}) "
        f"| Holdout 25-27: {h2527['pct']:5.1f}% ({h2527['w']}/{h2527['n']}) "
        f"| 26-27: {s2627['pct']:5.1f}% ({s2627['w']}/{s2627['n']}) "
        f"| L50: {l50['pct']:5.1f}% ({l50['w']}/{l50['n']}) | Edge: {h2527['edge']:+5.1f}pp"
    )

print("[5/5] Saving fusion_nhl_master.json, fusion_nhl_fast.json, fusion_modes_summary.json & fusion_roster_runtime.json...")
json.dump(
    {"games": master_games, "summary": summary, "fusion_modes_summary": summary},
    open(os.path.join(PUB_DIR, "fusion_nhl_master.json"), "w", encoding="utf-8"),
    ensure_ascii=False,
    separators=(",", ":"),
)
fast_games = [g for g in master_games if "2026-10-01" <= g["d"] <= "2027-01-15"]
json.dump(
    {"games": fast_games, "summary": summary, "fusion_modes_summary": summary},
    open(os.path.join(PUB_DIR, "fusion_nhl_fast.json"), "w", encoding="utf-8"),
    ensure_ascii=False,
    separators=(",", ":"),
)
json.dump(summary, open(os.path.join(PUB_DIR, "fusion_modes_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

prior_gp_2526 = {
    tm_n: {pid: vals[1] for pid, vals in pmap.items()}
    for tm_n, pmap in prior_2526_by_team.items()
}
p_static_out = {
    pid: {
        "pid": ps["pid"],
        "fn": ps["fn"],
        "jn": ps["jn"],
        "j_str": ps["j_str"],
        "pos": ps["pos"],
        "deg2": ps["deg2"],
        "deg3": ps["deg3"],
        "nam_fawe": list(ps["nam_fawe"]),
    }
    for pid, ps in p_static.items()
}
rt_out = {
    "team_tz_map": dict(TEAM_TO_TZ),
    "live_rosters": live_rosters,
    "base_mpg_2526": dict(base_mpg_2526),
    "prior_gp_2526": prior_gp_2526,
    "p_static": p_static_out,
    "player_static": p_static_out,
    "team_box_2627": dict(team_box_2627),
}
json.dump(rt_out, open(os.path.join(HERE, "fusion_roster_runtime.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"DONE in {time.time() - t0:.1f}s!")
