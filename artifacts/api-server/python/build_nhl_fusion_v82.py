#!/usr/bin/env python3
"""
Complete Zero-Lookahead NHL-FUSION-SIGNAL v82 Master Builder (2010–2027):
  1. Ingests seed `nhl_predictions_2024_2027.json` + `nhl_history_pack_2010_2026.json` + live 2026-27 ESPN NHL OT/SO results.
  2. Evaluates NHL Player Signal Mode C (`DEG1 = 88` [28 GEMINI / AIR], `DEG2 = egem(Full_Name)%360`, `DEG3 = Jersey_No%360`),
     weighted by `TOI` for Top-8 active players (max 1 goalie) and Top-12 active players (max 2 dressed goalies), filtering `OUT`/`IR`.
  3. Runs the 100% untouched v82 14-Mode Calculation Core (`recompute_all_fusion_modes`, `compute_total_elem_12_block`, `recompute_summary`).
  4. Emits `fusion_nhl_master.json`, `fusion_nhl_fast.json`, `fusion_modes_summary.json`,
     `player_nhl_preds_mode_c.json`, `player_nhl_hist_mode_c.json`, and `fusion_roster_runtime.json`.
"""
import bisect
import datetime
import json
import math
import os
import shutil
import sys
import time
from collections import defaultdict

import numpy as np

t0 = time.time()
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fusion_player_eval as pc
from fusion_roster_sync import (
    compute_total_elem_12_block,
    eval_team_lineup_exact,
    geo_code_from_ef_str,
    is_blocked_nhl_status,
    nls,
    recompute_all_fusion_modes,
    recompute_summary,
    score_5_player_fusion,
)
from nhl_teams import (
    NHL_DEG1,
    TEAM_META_32,
    TEAM_TO_ARENA,
    TEAM_TO_CODE,
    TEAM_TO_TZ,
    clean_ascii,
    norm_team,
    season_of_date,
)

PUB_DIR = os.path.abspath(os.path.join(HERE, "../../calc-dashboard/public"))
API_DATA_DIR = os.path.abspath(os.path.join(HERE, "../data"))
ROOT_DATA_DIR = os.path.abspath(os.path.join(HERE, "../../../data"))
os.makedirs(PUB_DIR, exist_ok=True)
os.makedirs(API_DATA_DIR, exist_ok=True)
os.makedirs(ROOT_DATA_DIR, exist_ok=True)

SEED_PRED = "/tmp/nhl_seed/nhl_predictions_2024_2027.json"
SEED_HIST = "/tmp/nhl_seed/nhl_history_pack_2010_2026.json"

if os.path.exists(SEED_HIST):
    shutil.copyfile(SEED_HIST, os.path.join(PUB_DIR, "nhl_history_pack_2010_2026.json"))
if os.path.exists(SEED_PRED):
    shutil.copyfile(SEED_PRED, os.path.join(PUB_DIR, "nhl_predictions_2024_2027.json"))

t_doc = json.load(open(os.path.join(PUB_DIR, "nhl_predictions_2024_2027.json"), "r", encoding="utf-8"))
t_hist_raw = json.load(open(os.path.join(PUB_DIR, "nhl_history_pack_2010_2026.json"), "r", encoding="utf-8"))
pb = json.load(open(os.path.join(HERE, "nhl_players_2010_2027.json"), "r", encoding="utf-8"))

player_master = pb["player_master"]
live_rosters = {norm_team(k): v for k, v in pb["live_rosters"].items()}
season_team_players = {}
for k_stp, plist in pb["season_team_players"].items():
    s_part, tm_part = k_stp.split("||", 1)
    ntm = norm_team(tm_part)
    season_team_players.setdefault(f"{s_part}||{ntm}", []).extend(plist)
events_2627 = pb["events_2627"]
boxscores_2627 = pb["boxscores_2627"]

# Sync fresh completed 2026-27 ESPN NHL scores (including OT/SO/shutouts) into t_doc
espn_2627_finals = {}
for ev in events_2627:
    if ev.get("completed") and ev["hp"] != ev["ap"]:
        espn_2627_finals[(ev["d"], norm_team(ev["h"]), norm_team(ev["a"]))] = (int(ev["hp"]), int(ev["ap"]), ev.get("ot", ""))

updated_seed_preds = 0
for pg in t_doc["games"]:
    hn, an = norm_team(pg["h"]), norm_team(pg["a"])
    fk = (pg["d"], hn, an)
    if fk in espn_2627_finals:
        hp_v, ap_v, ot_tag = espn_2627_finals[fk]
        aw_orig = pg["h"] if hp_v > ap_v else pg["a"]
        new_sc = f"{hp_v}-{ap_v} ({ot_tag})" if ot_tag else f"{hp_v}-{ap_v}"
        if not pg.get("done") or pg.get("hp") != hp_v or pg.get("ap") != ap_v:
            updated_seed_preds += 1
        pg["hp"], pg["ap"] = hp_v, ap_v
        pg["sc"] = new_sc
        if ot_tag:
            pg["ot"] = ot_tag
        pg["aw"] = aw_orig
        pg["done"] = True
        pg["hw"] = bool(hp_v > ap_v)
        pg["st"] = "WIN" if norm_team(pg.get("pw")) == norm_team(aw_orig) else "LOSS"
        pg["fst"] = "WIN" if norm_team(pg.get("fpw")) == norm_team(aw_orig) else "LOSS"

# Persist updated nhl_predictions_2024_2027.json across public & data dirs
for dst_p in [
    os.path.join(PUB_DIR, "nhl_predictions_2024_2027.json"),
    os.path.join(API_DATA_DIR, "nhl_predictions_2024_2027.json"),
    os.path.join(ROOT_DATA_DIR, "nhl_predictions_2024_2027.json"),
]:
    json.dump(t_doc, open(dst_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"[1/6] Seed NHL predictions loaded ({len(t_doc['games'])} games, +{updated_seed_preds} newly synced 2026-27 ESPN finals) in {time.time()-t0:.1f}s")

# Build unified chronological NHL game universe (2010-01-01 .. 2027-04-10)
games_by_key = {}
for row in t_hist_raw:
    d_iso = str(row[0]).strip()
    h = norm_team(row[3])
    a = norm_team(row[4])
    if h not in TEAM_META_32 or a not in TEAM_META_32:
        continue
    hp, ap = int(row[5]), int(row[6])
    if hp == ap:
        continue
    dt = datetime.date(*map(int, d_iso.split("-")))
    games_by_key[(d_iso, h, a)] = {
        "d": d_iso,
        "day": dt.strftime("%A").upper(),
        "s": season_of_date(d_iso),
        "h": h,
        "a": a,
        "hp": hp,
        "ap": ap,
        "ot": "",
        "done": True,
        "arena": TEAM_TO_ARENA.get(h, ""),
        "tz": TEAM_TO_TZ.get(h, "America/New_York"),
    }

t_map = {}
for pg in t_doc["games"]:
    d_iso = pg["d"]
    h = norm_team(pg["h"])
    a = norm_team(pg["a"])
    t_map[(d_iso, h, a)] = pg
    done = bool(pg.get("done") and pg.get("hp") is not None and pg.get("ap") is not None and int(pg["hp"]) != int(pg["ap"]))
    hp = int(pg.get("hp") or 0) if done else 0
    ap = int(pg.get("ap") or 0) if done else 0
    games_by_key[(d_iso, h, a)] = {
        "d": d_iso,
        "day": pg["day"],
        "s": pg["s"],
        "h": h,
        "a": a,
        "hp": hp,
        "ap": ap,
        "ot": pg.get("ot", ""),
        "done": done,
        "arena": pg.get("venue") or TEAM_TO_ARENA.get(h, ""),
        "tz": TEAM_TO_TZ.get(h, "America/New_York"),
    }

all_games = sorted(games_by_key.values(), key=lambda g: (g["d"], g["h"], g["a"]))
print(f"[2/6] Unified NHL game universe: {len(all_games)} games ({sum(1 for g in all_games if g['done'])} completed, {sum(1 for g in all_games if not g['done'])} pending)")

# Precompute per-player static metadata (DEG2 = egem(Full_Name)%360, DEG3 = Jersey_No%360)
p_static = {}
for pid, pm in player_master.items():
    fn = clean_ascii(pm.get("full_name") or "")
    if not fn:
        continue
    jn = clean_ascii(pm.get("jersey_name") or (fn.split()[-1] if fn else ""))
    j_str = str(pm.get("jersey") or "0").strip()
    spid = str(pid)
    p_static[spid] = {
        "pid": spid,
        "fn": fn,
        "jn": jn,
        "j_str": j_str if j_str != "" else "0",
        "pos": str(pm.get("pos") or ""),
        "status": str(pm.get("status") or "Healthy"),
        "deg2": pc.egem(fn) % 360,
        "deg3": pc.jersey_eff_num(j_str, zero_rule=True) % 360,
        "nam_fawe": list(pc.s4.word_element_fawe(fn)),
    }

# Index 2026-27 boxscores chronologically per team for strict pre-game rolling TOI rotation (b.d < g.d)
team_box_2627 = defaultdict(list)
for eid, bobj in boxscores_2627.items():
    d_b = bobj["d"]
    for tname, plist in bobj["box"].items():
        ntm = norm_team(tname)
        team_box_2627[ntm].append((d_b, plist))
for tname in team_box_2627:
    team_box_2627[tname].sort(key=lambda x: x[0])

live_roster_pids = {
    tname: {str(p["pid"]): p for p in plist}
    for tname, plist in live_rosters.items()
}

base_mpg_2526 = defaultdict(dict)
for k_stp, plist in season_team_players.items():
    s_part, tm_part = k_stp.split("||", 1)
    if s_part == "2025-26":
        for r in plist:
            base_mpg_2526[tm_part][str(r["pid"])] = float(r.get("mpg") or 16.0)


def prev_season(s_lbl: str) -> str:
    y0 = int(s_lbl[:4]) - 1
    return f"{y0}-{(y0 + 1) % 100:02d}"


def get_pregame_nhl_lineup(tname: str, s_lbl: str, d_iso: str, is_pending: bool, top_k: int = 8, max_goalies: int = 1):
    cur_roster = live_roster_pids.get(tname, {})
    if s_lbl == "2026-27":
        prior_games = [plist for (db, plist) in team_box_2627.get(tname, []) if db < d_iso]
        b_mpg = base_mpg_2526.get(tname, {})
        if prior_games:
            recent = prior_games[-10:]
            n_rec = max(1, len(recent))
            min_sums = defaultdict(float)
            gp_cnts = defaultdict(int)
            st_cnts = defaultdict(int)
            for plist in recent:
                for pr in plist:
                    pid = str(pr["pid"])
                    min_sums[pid] += float(pr["min"])
                    gp_cnts[pid] += 1
                    if pr.get("starter"):
                        st_cnts[pid] += 1
            cands = []
            all_pids = set(min_sums.keys()) | (set(cur_roster.keys()) if is_pending else set()) | set(b_mpg.keys())
            for pid in all_pids:
                if pid not in p_static:
                    continue
                if is_pending and cur_roster:
                    if pid not in cur_roster:
                        continue
                    if is_blocked_nhl_status(cur_roster[pid].get("status", "Healthy")):
                        continue
                pos = p_static[pid]["pos"]
                g_c = gp_cnts.get(pid, 0)
                obs_pg = (min_sums[pid] / g_c) if g_c > 0 else 0.0
                prior_m = float(b_mpg.get(pid, 24.0 if pos == "G" else 15.0))
                blend_toi = (g_c * obs_pg + 2.0 * prior_m) / (g_c + 2.0) if g_c > 0 else (prior_m * 0.65)
                rank_sc = (min_sums[pid] / n_rec) if pos == "G" else blend_toi
                if blend_toi >= 5.0:
                    is_st = st_cnts.get(pid, 0) >= max(1, g_c // 2) if g_c > 0 else (blend_toi >= 17.5)
                    cands.append((pid, round(blend_toi, 1), is_st, pos, rank_sc))
            cands.sort(key=lambda x: (x[3] == "G" and x[4] >= 25.0, x[4], x[1], x[0]), reverse=True)
            chosen = []
            g_used = 0
            for pid, toi_v, is_st, pos, _ in cands:
                if pos == "G":
                    if g_used >= max_goalies:
                        continue
                    g_used += 1
                chosen.append((pid, toi_v, is_st))
                if len(chosen) >= top_k:
                    break
            if len(chosen) >= 5:
                return chosen

    # Historical seasons (2009-10..2025-26) or Opening Night fallback (blend prior season + current season TOI)
    cur_list = season_team_players.get(f"{s_lbl}||{tname}", [])
    prv_list = season_team_players.get(f"{prev_season(s_lbl)}||{tname}", [])
    if not cur_list and prv_list:
        cur_list = prv_list
    prv_map = {str(r["pid"]): float(r.get("mpg") or 15.0) for r in prv_list}
    cands_h = []
    seen = set()
    for r in cur_list + prv_list:
        pid = str(r["pid"])
        if pid in seen or pid not in p_static:
            continue
        if is_pending and cur_roster:
            if pid not in cur_roster:
                continue
            if is_blocked_nhl_status(cur_roster[pid].get("status", "Healthy")):
                continue
        seen.add(pid)
        pos = p_static[pid]["pos"]
        cur_m = float(r.get("mpg") or 15.0)
        toi_v = (0.6 * prv_map[pid] + 0.4 * cur_m) if pid in prv_map else cur_m
        tot_m = float(r.get("tot_min") or (toi_v * 50.0))
        rank_sc = (tot_m / 55.0) if pos == "G" else toi_v
        cands_h.append((pid, round(max(6.0, toi_v), 1), pos, rank_sc))
    cands_h.sort(key=lambda x: (x[2] == "G" and x[3] >= 22.0, x[3], x[1], x[0]), reverse=True)
    out = []
    g_used = 0
    for idx_i, (pid, toi_v, pos, _) in enumerate(cands_h):
        if pos == "G":
            if g_used >= max_goalies:
                continue
            g_used += 1
        out.append((pid, toi_v, idx_i < 6))
        if len(out) >= top_k:
            break
    # Final fallback to live roster if historical season had sparse data
    if len(out) < top_k and cur_roster:
        for pid, rec in cur_roster.items():
            if pid in seen or pid not in p_static:
                continue
            if is_pending and is_blocked_nhl_status(rec.get("status", "Healthy")):
                continue
            pos = p_static[pid]["pos"]
            if pos == "G" and g_used >= max_goalies:
                continue
            if pos == "G":
                g_used += 1
            out.append((pid, 16.0, False))
            if len(out) >= top_k:
                break
    return out


# Precompute Weekly & Daily Standings Snapshots across 2010..2027 (zero lookahead!)
done_base_hist = [
    {"d": g["d"], "day": g["day"], "s": g["s"], "h": g["h"], "a": g["a"], "hp": g["hp"], "ap": g["ap"], "mg": g["hp"] - g["ap"]}
    for g in all_games if g["done"]
]
cut_pairs = set()
sched_set = set()
for g in all_games:
    sched_set.add((g["d"], g["h"]))
    sched_set.add((g["d"], g["a"]))
    cut_pairs.add((g["d"], g["s"]))
    if g["d"] >= "2024-10-01":
        dt = datetime.date(*map(int, g["d"].split("-")))
        mon = (dt - datetime.timedelta(days=dt.weekday())).isoformat()
        cut_pairs.add((mon, g["s"]))

all_snaps = nls.build_all_snapshots(done_base_hist, cut_pairs)
print(f"[3/6] Built {len(all_snaps)} zero-lookahead NHL standings snapshots in {time.time()-t0:.1f}s")


def fast_auto_filter_np(D, lim, t_vec, t_geo, g_key, geo_first, min_gf):
    idx = np.arange(lim, dtype=np.int32)
    m_mat = D["m12"]
    g_arr = D[g_key]
    used_geo = False
    if geo_first and t_geo > 0:
        nxt = idx[g_arr[idx] == t_geo]
        if len(nxt) >= min_gf:
            idx = nxt
            used_geo = True
    used = 0
    while len(idx) > 7:
        bc, bcnt, bnxt = -1, -1, None
        sub = m_mat[idx]
        for c in range(12):
            if (used >> c) & 1:
                continue
            tv = t_vec[c]
            if tv == 0:
                continue
            mask = (sub[:, c] == tv)
            cnt = int(mask.sum())
            if 5 <= cnt < len(idx) and cnt > bcnt:
                bc, bcnt, bnxt = c, cnt, idx[mask]
        if bc < 0:
            break
        used |= (1 << bc)
        idx = bnxt
        if 5 <= len(idx) <= 7:
            break
    if (not geo_first) and (not used_geo) and t_geo > 0 and len(idx) > 7:
        nxt = idx[g_arr[idx] == t_geo]
        if 5 <= len(nxt) <= 7:
            idx = nxt
    nat = (5 <= len(idx) <= 7)
    chosen = idx if len(idx) <= 7 else idx[-7:]
    pool_rows = [D["rows"][int(i)] for i in chosen]
    hw, aw, d_raw, s_delta, eff = nls.pool_idx_ds(pool_rows)
    tot = max(1, hw + aw)
    pct = round(max(hw, aw) * 100.0 / tot, 1)
    return {
        "pool": pool_rows, "hw": hw, "aw": aw, "pct": pct, "mv": abs(hw - aw),
        "nat": nat, "ds": eff, "d_raw": d_raw, "s_delta": s_delta,
    }


print("[4/6] Evaluating NHL Top-8 & Top-12 TOI player lineups (DEG1=88) across 2010..2027...")
vocab = {}


def vid(s: str) -> int:
    if not s:
        return 0
    v = vocab.get(s)
    if v is None:
        v = len(vocab) + 1
        vocab[s] = v
    return v


mode_rows = []
for g in all_games:
    is_pend = not g["done"]
    is_target = (g["d"] >= "2024-10-01")
    hl8 = get_pregame_nhl_lineup(g["h"], g["s"], g["d"], is_pend, top_k=8, max_goalies=1)
    al8 = get_pregame_nhl_lineup(g["a"], g["s"], g["d"], is_pend, top_k=8, max_goalies=1)
    d_ctx = pc.get_date_ctx(g["d"])
    tbl_u = d_ctx[8]
    h12, h_fin, h_dyn, mh_u, h_pcards = eval_team_lineup_exact(d_ctx, hl8, tbl_u, p_static)
    a12, a_fin, a_dyn, ma_u, a_pcards = eval_team_lineup_exact(d_ctx, al8, tbl_u, p_static)

    snap_dy = all_snaps[(g["d"], g["s"])]
    h_tab, a_tab = nls.geo_tab_pair(snap_dy, g["h"], g["a"])

    mv, f30, ag5 = [0, 0, 0, 0, 0], 0, 3
    t12_blk = None
    if is_target:
        y, m, d = map(int, g["d"].split("-"))
        jd_l = pc.get_jd_local(y, m, d, g["tz"], 19, 30)
        tbl_l = pc.get_deg_table(jd_l)
        _, _, _, mh_l, _ = eval_team_lineup_exact(d_ctx, hl8, tbl_l, p_static)
        _, _, _, ma_l, _ = eval_team_lineup_exact(d_ctx, al8, tbl_l, p_static)
        mv, f30, ag5 = score_5_player_fusion(mh_u, ma_u, mh_l, ma_l)

        hl12 = get_pregame_nhl_lineup(g["h"], g["s"], g["d"], is_pend, top_k=12, max_goalies=2)
        al12 = get_pregame_nhl_lineup(g["a"], g["s"], g["d"], is_pend, top_k=12, max_goalies=2)
        t12_blk = compute_total_elem_12_block(
            d_ctx, tbl_l, g["h"], g["a"], hl12, al12, p_static,
            include_players=(g["s"] == "2026-27"),
        )

    mode_rows.append({
        "g": g,
        "h12": h12, "a12": a12,
        "h_fin": h_fin, "h_dyn": h_dyn, "h_tab": h_tab,
        "a_fin": a_fin, "a_dyn": a_dyn, "a_tab": a_tab,
        "v_h12": [vid(x) for x in h12],
        "v_hfin": vid(h_fin), "v_hdyn": vid(h_dyn), "v_htab": vid(h_tab),
        "mv": mv, "f30": f30, "ag5": ag5,
        "h_pcards": h_pcards if is_target else None,
        "a_pcards": a_pcards if is_target else None,
        "t12_blk": t12_blk,
    })

by_day = defaultdict(list)
hist_pack_out = []
for mr in mode_rows:
    g = mr["g"]
    if g["done"]:
        mg = g["hp"] - g["ap"]
        rec_h = {
            "d": g["d"], "day": g["day"], "s": g["s"],
            "h": g["h"], "a": g["a"], "hp": g["hp"], "ap": g["ap"], "mg": mg,
            "h12": mr["h12"], "h_fin": mr["h_fin"], "h_dyn": mr["h_dyn"], "h_tab": mr["h_tab"],
            "v_h12": mr["v_h12"], "v_hfin": mr["v_hfin"], "v_hdyn": mr["v_hdyn"], "v_htab": mr["v_htab"],
        }
        by_day[g["day"]].append(rec_h)
        hist_pack_out.append([
            g["d"], g["day"], g["s"], g["h"], g["a"], g["hp"], g["ap"], mg,
            mr["h12"], mr["h_dyn"], mr["a12"], mr["a_dyn"],
            mr["f30"], "", mr["h_tab"], mr["a_tab"],
        ])

day_np = {}
for wd_k, lst in by_day.items():
    day_np[wd_k] = {
        "dates": [x["d"] for x in lst],
        "rows": lst,
        "m12": np.array([x["v_h12"] for x in lst], dtype=np.int32),
        "fin": np.array([x["v_hfin"] for x in lst], dtype=np.int32),
        "dyn": np.array([x["v_hdyn"] for x in lst], dtype=np.int32),
        "tab": np.array([x["v_htab"] for x in lst], dtype=np.int32),
    }

SHAMSI_MONTHS = ["", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def _g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053)); days %= 12053
    jy += 4 * (days // 1461); days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31); jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30); jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def parse_votes(g_obj):
    v = str(g_obj.get("twVotes", "0H-0A"))
    try:
        hp_s, ap_s = v.replace("A", "").split("H-")
        return int(hp_s), int(ap_s)
    except Exception:
        return 0, 0


print("[5/6] Running zero-lookahead Twin Engine & 14-Mode v82 Fusion across all 2024–2027 NHL games...")
player_preds_out = []
master_games = []
game_num = 0

for mr in mode_rows:
    g = mr["g"]
    if g["d"] < "2024-10-01":
        continue
    k_match = (g["d"], g["h"], g["a"])
    gt = t_map.get(k_match)
    if gt is None:
        continue
    game_num += 1
    D = day_np[g["day"]]
    lim = bisect.bisect_left(D["dates"], g["d"])

    sd = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_hdyn"], "dyn", False, 3)
    gd3 = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_hdyn"], "dyn", True, 3)
    f30_p = mr["f30"]
    ag5_p = mr["ag5"]
    sa = (sd["hw"] >= sd["aw"]) == (f30_p >= 0)
    ga = (gd3["hw"] >= gd3["aw"]) == (f30_p >= 0)
    pick_geo = (
        False if (sd["pct"] < 60 or (sa and not ga and sd["pct"] >= 55))
        else True if (not sa and ga and gd3["pct"] >= 55)
        else (gd3["pct"] > sd["pct"] or (gd3["pct"] == sd["pct"] and gd3["mv"] > sd["mv"]))
    )
    ch = gd3 if pick_geo else sd
    hw, aw_c, nat = ch["hw"], ch["aw"], ch["nat"]
    tot = hw + aw_c
    pct_int = round(max(hw, aw_c) * 100 / tot) if tot else 50
    hfav_p = True if hw > aw_c else (False if aw_c > hw else f30_p >= 0)
    sgn_p = 1 if hfav_p else -1
    ppk = g["h"] if hfav_p else g["a"]
    popp = g["a"] if hfav_p else g["h"]
    f30_po = f30_p * sgn_p
    agree = (hfav_p and f30_p > 0) or (not hfav_p and f30_p < 0)
    both100 = sd["pct"] == 100.0 and gd3["pct"] == 100.0 and ((sd["hw"] > 0) == (gd3["hw"] > 0))
    v71 = 5 <= tot <= 7 and pct_int >= 71 and abs(hw - aw_c) >= 3
    bcombo = v71 and (agree or both100)

    c1 = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_hfin"], "fin", False, 5)
    c2 = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_hfin"], "fin", True, 5)
    c3 = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_hdyn"], "dyn", True, 5)
    c4 = fast_auto_filter_np(D, lim, mr["v_h12"], mr["v_htab"], "tab", True, 5)

    ds4 = [c1["ds"], c2["ds"], c3["ds"], c4["ds"]]
    ds4_o = [v * sgn_p for v in ds4]
    ds3_o = ds4_o[:3]
    vh4 = sum(1 for v in ds4 if v > 0); va4 = sum(1 for v in ds4 if v < 0)
    nat4 = sum(1 for cx in (c1, c2, c3, c4) if cx["nat"])
    fav_v4 = vh4 if hfav_p else va4; opp_v4 = va4 if hfav_p else vh4
    fav_v3 = sum(1 for v in ds3_o if v > 0); opp_v3 = sum(1 for v in ds3_o if v < 0)
    min_o4 = min(ds4_o); min_o3 = min(ds3_o)

    y, m, d = map(int, g["d"].split("-"))
    dt = datetime.date(y, m, d)
    mon = (dt - datetime.timedelta(days=dt.weekday())).isoformat()
    yest = (dt - datetime.timedelta(days=1)).isoformat()
    pb2b = (yest, ppk) in sched_set and (yest, popp) not in sched_set
    ob2b = (yest, popp) in sched_set and (yest, ppk) not in sched_set
    is_playoff = (g["d"][5:10] >= "04-15" and m <= 6)
    c4_vote_opp = ((c4["hw"] - c4["aw"]) * sgn_p < 0)

    t1 = (not hfav_p) and (f30_po < 10 or (fav_v3 < 2 and fav_v4 < 3))
    t2 = (opp_v3 >= 2 and f30_po < 8) or (opp_v4 >= 2 and f30_po < 10)
    t3 = pb2b and f30_po < 12 and ((not hfav_p) or (not nat))
    t4 = (not nat) and fav_v3 < 3 and fav_v4 < 3 and f30_po < 12
    t5 = (fav_v4 == 0) or (c4_vote_opp and f30_po < 12) or (is_playoff and (ag5_p < 4 or not nat))
    htrap = t1 or t2 or t3 or t4 or t5
    g4 = bool(bcombo and not htrap)
    c4_hfav = c4["hw"] > c4["aw"]
    c4_resc = (
        (not bcombo)
        and 5 <= (c4["hw"] + c4["aw"]) <= 7
        and c4["nat"] and c4["pct"] >= 83
        and c4_hfav == hfav_p and f30_po >= 10 and c4["ds"] * sgn_p >= 2
        and not is_playoff and not pb2b
    )
    resc = bool(((not bcombo) and v71 and fav_v4 >= 3 and min_o3 >= 1 and not htrap) or c4_resc)

    snap_wk = all_snaps[(mon, g["s"])]
    snap_dy = all_snaps[(g["d"], g["s"])]
    wtp_wk_p = nls.make_wtp_obj(snap_wk, mon, g["h"], g["a"], hfav_p)
    wtp_dy_p = nls.make_wtp_obj(snap_dy, yest, g["h"], g["a"], hfav_p)

    p_sig = bool(g4 and wtp_wk_p["mel"] != "EARTH")
    p_vip = bool(g4 and wtp_wk_p["mel"] != "EARTH" and (wtp_wk_p["mel"] == "FIRE" or (nat and fav_v4 == 4 and min_o4 >= 2)))
    p_union = bool((g4 or resc) and wtp_wk_p["mel"] != "EARTH")

    # Team Engine from seed `nhl_predictions_2024_2027.json` (DEG1 = 88)
    tpk = norm_team(gt.get("fpw") or gt.get("pw") or g["h"])
    f30_t = int(gt.get("f30") if gt.get("f30") is not None else 0)
    t_sig = bool(gt.get("f1_wtp"))
    t_vip = bool(gt.get("vip_idx3"))
    sgn_t = 1 if tpk == g["h"] else -1

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

    hfav_dp = (pk_dp == g["h"])
    wtp_wk = nls.make_wtp_obj(snap_wk, mon, g["h"], g["a"], hfav_dp)
    wtp_dy = nls.make_wtp_obj(snap_dy, yest, g["h"], g["a"], hfav_dp)

    aw_team = (g["h"] if g["hp"] > g["ap"] else g["a"]) if g["done"] else "PENDING"
    sc_lbl = (f"{g['hp']}-{g['ap']} ({g['ot']})" if g.get("ot") else f"{g['hp']}-{g['ap']}") if g["done"] else "PENDING"

    jy, jm, jd = _g2j(y, m, d)
    sh_d = gt.get("sh_d") or f"{jy}/{jm:02d}/{jd:02d}"
    sh_m = f"{jy}-{jm:02d} ({SHAMSI_MONTHS[jm]})"

    h_out, a_out = [], []
    if g["d"] >= "2026-11-15":
        for side_tm, out_arr in [(g["h"], h_out), (g["a"], a_out)]:
            for p_r in live_rosters.get(side_tm, []):
                st_r = str(p_r.get("status", "")).strip()
                if is_blocked_nhl_status(st_r) and p_r.get("full_name"):
                    tag = f" • {st_r.upper()}" if st_r.lower() != "out" else ""
                    jer_s = p_r.get("jersey", "")
                    out_arr.append(f"{p_r['full_name']} (#{jer_s}{tag})" if jer_s else f"{p_r['full_name']}{tag}")

    hp_cards = mr["h_pcards"] or []
    ap_cards = mr["a_pcards"] or []
    for pl in hp_cards + ap_cards:
        pl["gf"] = geo_code_from_ef_str(pl["ef"])

    p_idx_obj = {
        "st": [c1["hw"], c1["aw"], c1["ds"]],
        "gf": [c2["hw"], c2["aw"], c2["ds"]],
        "gd": [c3["hw"], c3["aw"], c3["ds"]],
        "gt": [c4["hw"], c4["aw"], c4["ds"]],
        "tw": [hw, aw_c, ch["ds"]],
        "vh": vh4, "va": va4, "nat": nat4, "minD": min_o4,
    }
    t_idx_obj = gt.get("idx3") or p_idx_obj

    dir_mgs = sorted([abs(x["mg"]) for x in ch["pool"] if (x["mg"] > 0) == hfav_p])
    tp_arr = [
        int(dir_mgs[max(0, len(dir_mgs) // 4)]),
        int(dir_mgs[len(dir_mgs) // 2]),
        int(dir_mgs[min(len(dir_mgs) - 1, (3 * len(dir_mgs)) // 4)]),
    ] if dir_mgs else [1, 2, 3]

    p_pred_obj = {
        "n": game_num,
        "day": g["day"], "d": g["d"], "ym": g["d"][:7], "s": g["s"],
        "sh_d": sh_d, "sh_m": sh_m,
        "h": g["h"], "a": g["a"],
        "hc": TEAM_TO_CODE.get(g["h"], gt.get("hc", "")),
        "ac": TEAM_TO_CODE.get(g["a"], gt.get("ac", "")),
        "venue": g["arena"],
        "hp": g["hp"], "ap": g["ap"], "sc": sc_lbl,
        "pw": ppk, "fpw": ppk, "sys_win": ppk, "twWin": ppk,
        "aw": aw_team,
        "st": ("WIN" if ppk == aw_team else "LOSS") if g["done"] else "PENDING",
        "fst": ("WIN" if ppk == aw_team else "LOSS") if (g["done"] and p_sig) else ("PENDING" if not g["done"] else ""),
        "done": g["done"], "hw": (g["hp"] > g["ap"]) if g["done"] else None,
        "ph": hfav_p, "vm6": f30_p, "f30": f30_p, "a25": f30_p, "ag5": ag5_p, "mv": mr["mv"], "v": mr["mv"], "nd": abs(f30_p),
        "twMode": "GEO" if pick_geo else "STEP",
        "twVotes": f"{hw}H-{aw_c}A", "twPct": f"{pct_int}%", "tp": tp_arr, "twAgree": agree,
        "twins": [[x["d"], x["h"], x["a"], x["hp"], x["ap"], x["mg"]] for x in ch["pool"]],
        "twPeers": [f"{x['d']} | {x['h']} {x['hp']}-{x['ap']} {x['a']}" for x in ch["pool"]],
        "h_12": mr["h12"], "h_geo": mr["h_fin"], "h_geo_dyn": mr["h_dyn"], "h_geo_tab": mr["h_tab"],
        "a_12": mr["a12"], "a_geo": mr["a_fin"], "a_geo_dyn": mr["a_dyn"], "a_geo_tab": mr["a_tab"],
        "b2b_tag": "B2B_PICK" if pb2b else ("B2B_OPP" if ob2b else ""),
        "is_nat": bool(nat),
        "trap_tag": gt.get("trap_tag", ""),
        "f1": bool(bcombo), "f1_idx": bool(bcombo and (ch["ds"] * sgn_p > 0)),
        "f1_guard": g4, "idx_rescue": resc,
        "f1_wtp": p_sig, "vip_idx3": p_vip, "f1_union": p_union,
        "f1_wtp_day": bool(g4 and wtp_dy_p["mel"] != "EARTH"),
        "vip_idx3_day": bool(g4 and wtp_dy_p["mel"] != "EARTH" and (wtp_dy_p["mel"] == "FIRE" or (nat and fav_v4 == 4 and min_o4 >= 2))),
        "f1_union_day": bool((g4 or resc) and wtp_dy_p["mel"] != "EARTH"),
        "idx3": p_idx_obj,
        "wtp": wtp_wk_p, "wtp_day": wtp_dy_p,
        "p_mode": "mode_c",
        "deg": gt.get("deg") or [NHL_DEG1, TEAM_META_32[g["h"]]["deg2"], TEAM_META_32[g["h"]]["deg3"], TEAM_META_32[g["a"]]["deg2"], TEAM_META_32[g["a"]]["deg3"], TEAM_META_32[g["h"]]["deg2"], TEAM_META_32[g["a"]]["deg2"], TEAM_META_32[g["h"]]["deg3"]],
        "h_players": hp_cards, "a_players": ap_cards,
        "h_out": h_out, "a_out": a_out,
    }
    player_preds_out.append(p_pred_obj)

    # Build Fusion Master Game Object (preserving Team h_12/a_12/twins when Team drives, or Player when Player drives)
    g_out = dict(p_pred_obj)
    if gt.get("h_12"):
        g_out["h_12"] = gt["h_12"]
        g_out["h_geo"] = gt.get("h_geo") or g_out["h_geo"]
        g_out["h_geo_dyn"] = gt.get("h_geo_dyn") or g_out["h_geo_dyn"]
    if gt.get("a_12"):
        g_out["a_12"] = gt["a_12"]
        g_out["a_geo"] = gt.get("a_geo") or g_out["a_geo"]
        g_out["a_geo_dyn"] = gt.get("a_geo_dyn") or g_out["a_geo_dyn"]
    if gt.get("twins"):
        g_out["twins"] = gt["twins"]
        g_out["twPeers"] = gt.get("twPeers") or g_out["twPeers"]

    if is_diamond:
        thw, taw = parse_votes(gt); phw, paw = parse_votes(p_pred_obj)
        shw, saw = thw + phw, taw + paw
        g_out["twVotes"] = f"{shw}H-{saw}A"
        g_out["twPct"] = f"{round(100 * max(shw, saw) / max(1, shw + saw))}%"
    elif driver in ("TEAM", "BOTH"):
        g_out["twVotes"] = gt.get("twVotes", p_pred_obj["twVotes"])
        g_out["twPct"] = gt.get("twPct", p_pred_obj["twPct"])

    g_out["idx3"] = t_idx_obj if driver in ("TEAM", "BOTH") else p_idx_obj
    g_out["wtp"] = wtp_wk
    g_out["wtp_day"] = wtp_dy
    g_out["f30"] = int(f30_t + f30_p)
    g_out["vm6"] = int(f30_t + f30_p)
    g_out["twWin"] = pk_dp

    g_out["fusion_meta"] = {
        "mode": "dual_pillar",
        "tier": tier_code,
        "tier_fa": tier_fa,
        "driver": driver,
        "in_auth_overlap": True,
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
            "ch": f"{t_idx_obj.get('vh', 0)}H-{t_idx_obj.get('va', 0)}A",
            "sig": t_sig,
            "vip": t_vip,
            "deg2": TEAM_META_32[g["h"]]["deg2"],
            "deg3": TEAM_META_32[g["h"]]["deg3"],
        },
        "player": {
            "pick": ppk,
            "votes": f"{hw}H-{aw_c}A",
            "pct": f"{pct_int}%",
            "f30": f30_p,
            "ch": f"{vh4}H-{va4}A",
            "sig": p_sig,
            "vip": p_vip,
        },
    }
    if mr["t12_blk"]:
        g_out["fusion_meta"]["total_elem_12"] = mr["t12_blk"]

    recompute_all_fusion_modes(g_out)
    master_games.append(g_out)

summary = recompute_summary(master_games)

print("[6/6] Writing NHL v82 Fusion Master, Fast, Player Mode C, Summary & Runtime JSONs...")
json.dump({"games": player_preds_out}, open(os.path.join(PUB_DIR, "player_nhl_preds_mode_c.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
json.dump(hist_pack_out, open(os.path.join(PUB_DIR, "player_nhl_hist_mode_c.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
json.dump({"games": master_games, "summary": summary, "fusion_modes_summary": summary}, open(os.path.join(PUB_DIR, "fusion_nhl_master.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

fast_games = [g for g in master_games if "2026-10-01" <= g["d"] <= "2027-01-15"]
json.dump({"games": fast_games, "summary": summary, "fusion_modes_summary": summary}, open(os.path.join(PUB_DIR, "fusion_nhl_fast.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
json.dump(summary, open(os.path.join(PUB_DIR, "fusion_modes_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

rt_out = {
    "team_tz_map": dict(TEAM_TO_TZ),
    "live_rosters": live_rosters,
    "base_mpg_2526": dict(base_mpg_2526),
    "team_box_2627": {tn: arr[-15:] for tn, arr in team_box_2627.items()},
    "player_static": {
        pid: {
            "fn": ps["fn"], "jn": ps["jn"], "j_str": ps["j_str"], "pos": ps["pos"],
            "deg2": ps["deg2"], "deg3": ps["deg3"], "nam_fawe": ps["nam_fawe"],
        }
        for pid, ps in p_static.items()
    },
    "extra_p_by_day": {},
}
json.dump(rt_out, open(os.path.join(HERE, "fusion_roster_runtime.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

print(f"\n=== NHL-FUSION-SIGNAL v82 14-MODE BACKTEST SUMMARY ({len(master_games)} games, {sum(1 for g in master_games if g['done'])} completed) ===")
for mk, st in summary.items():
    ho = st["holdout_2527"]
    s25 = st["s2526"]
    s26 = st["s2627"]
    l50 = st["last50"]
    print(f"  {mk:<18} | Holdout 25-27: {ho['pct']:>5}% ({ho['w']}/{ho['n']}) | 25-26: {s25['pct']:>5}% ({s25['w']}/{s25['n']}) | 26-27: {s26['pct']:>5}% ({s26['w']}/{s26['n']}) | Last50: {l50['pct']:>5}% ({l50['w']}/{l50['n']}) | Edge: {ho['edge']:+.1f}pp")
print(f"\nDONE in {time.time()-t0:.1f}s!")
