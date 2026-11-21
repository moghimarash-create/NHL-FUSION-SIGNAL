"""Automatically syncs scheduled NHL games from NHL_SCHEDULE_2025_2027 into NHL-FUSION-INPUT!Sheet1.

Writes 2 rows per game in Sheet1:
  - Row 1 (HOME): TEAM = Home Team, HOST_TEAM = Home Team -> DEG2 = Home Team DEG2, ARENA_DEG3 = Host Arena DEG3, EL1/EL2 for Home
  - Row 2 (AWAY): TEAM = Away Team, HOST_TEAM = Home Team -> DEG2 = Away Team DEG2, ARENA_DEG3 = Host Arena DEG3, EL1/EL2 for Away
"""
import argparse
import re
import sys
import traceback
import json
import os
from datetime import datetime
from _lib.runner import emit_result, log
from _lib.sheets import open_sheet
from nhl_teams import TEAM_META_32, egem

SPREADSHEET_ID = os.environ.get("NHL_FUSION_INPUT_SHEET_ID", "").strip()
SCHEDULE_TAB = os.environ.get("NHL_SCHEDULE_TAB", "NHL_SCHEDULE_2025_2027")

_ZODIAC_SIGNS = [
    "ARIES", "TAURUS", "GEMINI", "CANCER", "LEO", "VIRGO",
    "LIBRA", "SCORPIO", "SAGITTARIUS", "CAPRICORN", "AQUARIUS", "PISCES",
]
TEAM_CODE_DEG2 = {
    tm: (meta["code"], egem(meta["code"]) % 360, f"{(egem(meta['code']) % 360) % 30} {_ZODIAC_SIGNS[(egem(meta['code']) % 360) // 30]}")
    for tm, meta in TEAM_META_32.items()
}


WEEKDAY_NUM = {
    "MONDAY": 9, "TUESDAY": 5, "WEDNESDAY": 8,
    "THURSDAY": 4, "FRIDAY": 7, "SATURDAY": 6, "SUNDAY": 3,
}
ARCANUM_TO_CARD = {
    1:  "Scorpio - [Water]",   2:  "Leo - [Fire]",
    3:  "Gemini - [Air]",      4:  "Aries - [Fire]",
    5:  "Gemini - [Air]",      6:  "Gemini - [Air]",
    7:  "Capricorn - [Earth]", 8:  "Libra - [Air]",
    9:  "Capricorn - [Earth]", 10: "Gemini - [Air]",
    11: "Taurus - [Earth]",    12: "Cancer - [Water]",
    13: "Gemini - [Air]",      14: "Leo - [Fire]",
    15: "Aries - [Fire]",      16: "Gemini - [Air]",
    17: "Taurus - [Earth]",    18: "Scorpio - [Water]",
    19: "Capricorn - [Earth]", 20: "Leo - [Fire]",
    21: "Aquarius - [Air]",    22: "Virgo - [Earth]",
}
ELEMENT_QUALITIES = {
    "Fire":  ("HOT",  "DRY"),
    "Earth": ("COLD", "DRY"),
    "Air":   ("HOT",  "MOIST"),
    "Water": ("COLD", "MOIST"),
}


def sheets_retry(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _parse_mdy(s: str):
    s = str(s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _vlookup_formula(col_letter: str, row_idx: int, col_num: int) -> str:
    return '=IFERROR(VLOOKUP(' + col_letter + str(row_idx) + ", 'NBA-GEM'!$A$2:$Z$31, " + str(col_num) + ', FALSE), "")'


def _calc_f_and_el(date_mdy: str, weekday_str: str, deg1: int, deg2: int, deg3: int):
    try:
        m, d, y = [int(x) for x in str(date_mdy).strip().split("/")]
        d_sum = sum(int(c) for c in f"{y:04d}{m:02d}{d:02d}")
    except Exception:
        d_sum = 20
    w_num = WEEKDAY_NUM.get(str(weekday_str).strip().upper(), 3)
    fh = w_num + d_sum
    f1, f2, f3 = int(deg1) + fh, int(deg2) + fh, int(deg3) + fh
    main_pairs, sub_pairs = [], []
    for p in (f1, f2, f3):
        r = int(p) % 22
        arc = 22 if r == 0 else r
        card = ARCANUM_TO_CARD[arc]
        elem = re.search(r"\[(\w+)\]", card).group(1)
        prim, sec = ELEMENT_QUALITIES[elem]
        main_pairs.append((arc, prim))
        sub_pairs.append((arc, sec))

    def _net(pairs, pos_l, neg_l):
        pos = sum(n for n, t in pairs if t == pos_l)
        neg = sum(n for n, t in pairs if t == neg_l)
        diff = pos - neg
        return f"{diff} {pos_l}" if diff > 0 else (f"{abs(diff)} {neg_l}" if diff < 0 else "0 NEUTRAL")

    return f1, f2, f3, _net(main_pairs, "HOT", "COLD"), _net(sub_pairs, "MOIST", "DRY")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="2025-01-09")
    ap.add_argument("--end-date", default="2025-01-12")
    ap.add_argument("--utc-control", default="0")
    ap.add_argument("--deg1", type=int, default=88)
    ap.add_argument("--deg2-mode", default="full")
    ap.add_argument("--lat", type=float, default=0.0)
    ap.add_argument("--lon", type=float, default=0.0)
    ap.add_argument("--time", default="")
    ap.add_argument("--tz", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    start_ymd = _parse_mdy(args.start_date) or "2025-01-09"
    end_ymd = _parse_mdy(args.end_date) or start_ymd
    if end_ymd < start_ymd:
        end_ymd = start_ymd
    utc_ctrl = str(args.utc_control).strip() in ("1", "true", "True", "yes")

    try:
        has_sa = bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and SPREADSHEET_ID)
        ss = None
        if has_sa:
            ss = open_sheet(SPREADSHEET_ID)
            sched_ws = ss.worksheet(SCHEDULE_TAB)
            sched_rows = sheets_retry(
                sched_ws.get_values,
                "A1:T5000",
                value_render_option="FORMATTED_VALUE",
            )
        else:
            local_sched = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_2025_2027.json")
            sched_rows = json.load(open(local_sched, "r", encoding="utf-8")).get("values", [])
        if not sched_rows or len(sched_rows) < 2:
            emit_result(ok=False, rows_written=0, error="NHL schedule is empty")
            return 1

        matched = []
        for r in sched_rows[1:]:
            if not r or not str(r[0]).strip():
                continue
            ymd = _parse_mdy(r[0])
            if start_ymd <= ymd <= end_ymd:
                matched.append(r)

        if not matched:
            emit_result(
                ok=False,
                rows_written=0,
                error=f"No NHL games scheduled between {start_ymd} and {end_ymd} in {SCHEDULE_TAB}",
            )
            return 1

        headers = [
            "DATE", "PRIC-CH", "WEEKDAY", "TEAM", "ROLE", "HOST_TEAM",
            "DEG1", "DEG2", "ARENA_DEG3",
            "F", "F2", "F3", "EL1", "EL2",
            "ARENA_NAME", "Time", "Zone", "Lat", "Lon",
            "OPPONENT", "TEAM_SCORE", "OPP_SCORE", "WINNER", "GAME_ID"
        ]
        out_rows = [headers]
        preview_games = []
        row_cursor = 2

        for r in matched:
            while len(r) < 20:
                r.append("")
            dt_str = r[0]
            wk = r[2]
            home_t = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", str(r[3]).strip())
            away_t = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", str(r[4]).strip())
            deg1_v = args.deg1 if args.deg1 else (int(r[5]) if str(r[5]).isdigit() else 88)
            use_code_deg2 = str(args.deg2_mode).strip().lower() == "code"
            deg2_vlookup_col = 25 if use_code_deg2 else 4
            if use_code_deg2 and home_t in TEAM_CODE_DEG2:
                h_deg2 = TEAM_CODE_DEG2[home_t][1]
            else:
                h_deg2 = int(float(r[6])) if str(r[6]).strip() != "" else 0
            if use_code_deg2 and away_t in TEAM_CODE_DEG2:
                a_deg2 = TEAM_CODE_DEG2[away_t][1]
            else:
                a_deg2 = int(float(r[7])) if str(r[7]).strip() != "" else 0
            arena_deg3 = int(float(r[8])) if str(r[8]).strip() != "" else 0
            tm_str = "00:00" if utc_ctrl else r[10]
            hs = str(r[16]).strip()
            as_ = str(r[17]).strip()
            if hs.isdigit() and as_.isdigit() and (int(hs) > 0 or int(as_) > 0) and int(hs) != int(as_):
                hp, ap = int(hs), int(as_)
                win_nm = home_t if hp > ap else away_t
                h_pch = f"{home_t} {hp}-{ap} {away_t} ({hp-ap:+d} | WIN: {win_nm})"
                a_pch = f"{away_t} {ap}-{hp} {home_t} ({ap-hp:+d} | WIN: {win_nm})"
            else:
                h_pch = f"{home_t} [HOME] vs {away_t} [AWAY]"
                a_pch = f"{away_t} [AWAY] @ {home_t} [HOME]"

            # Row 1: HOME TEAM (DEG2 = Home Team DEG2, ARENA_DEG3 = Host Stadium DEG3)
            hf1, hf2, hf3, hel1, hel2 = _calc_f_and_el(dt_str, wk, deg1_v, h_deg2, arena_deg3)
            r_h = row_cursor
            out_rows.append([
                dt_str, h_pch, wk, home_t, "HOME", home_t,
                deg1_v,
                _vlookup_formula("D", r_h, deg2_vlookup_col),
                _vlookup_formula("F", r_h, 14),
                hf1, hf2, hf3, hel1, hel2,
                _vlookup_formula("F", r_h, 8),
                tm_str,
                "UTC" if utc_ctrl else _vlookup_formula("F", r_h, 24),
                _vlookup_formula("F", r_h, 22),
                _vlookup_formula("F", r_h, 23),
                away_t, hs, as_, r[18], r[19],
            ])
            row_cursor += 1

            # Row 2: AWAY TEAM (DEG2 = Away Team DEG2, ARENA_DEG3 = Host Stadium DEG3!)
            af1, af2, af3, ael1, ael2 = _calc_f_and_el(dt_str, wk, deg1_v, a_deg2, arena_deg3)
            r_a = row_cursor
            out_rows.append([
                dt_str, a_pch, wk, away_t, "AWAY", home_t,
                deg1_v,
                _vlookup_formula("D", r_a, deg2_vlookup_col),
                _vlookup_formula("F", r_a, 14),
                af1, af2, af3, ael1, ael2,
                _vlookup_formula("F", r_a, 8),
                tm_str,
                "UTC" if utc_ctrl else _vlookup_formula("F", r_a, 24),
                _vlookup_formula("F", r_a, 22),
                _vlookup_formula("F", r_a, 23),
                home_t, as_, hs, r[18], r[19],
            ])
            row_cursor += 1

            preview_games.append({
                "date": dt_str,
                "weekday": wk,
                "time": tm_str,
                "homeTeam": f"{home_t} (EL: {hel1}, {hel2})",
                "awayTeam": f"{away_t} (EL: {ael1}, {ael2})",
                "deg1": deg1_v,
                "homeDeg2": str(h_deg2),
                "awayDeg2": str(a_deg2),
                "arenaDeg3": str(arena_deg3),
                "arena": r[9],
                "tz": "UTC" if utc_ctrl else r[11],
                "lat": r[12],
                "lon": r[13],
                "season": r[14],
                "gameType": r[15],
                "homeScore": hs,
                "awayScore": as_,
                "winner": r[18],
            })

        if ss is not None:
            ws = ss.sheet1
            sheets_retry(ws.clear)
            if ws.row_count < len(out_rows) + 10 or ws.col_count < 24:
                sheets_retry(ws.resize, rows=max(len(out_rows) + 20, 100), cols=24)
            sheets_retry(
                ws.update,
                range_name=f"A1:X{len(out_rows)}",
                values=out_rows,
                value_input_option="USER_ENTERED",
            )

        msg = (
            f"Synced {len(matched)} NHL games ({len(out_rows)-1} Home/Away rows: {start_ymd} to {end_ymd}) "
            f"from {SCHEDULE_TAB} (DEG1={args.deg1}, DEG2 Mode: {'3-Letter Code' if str(args.deg2_mode).strip().lower()=='code' else 'Full Team Name'})"
        )
        log(msg)
        emit_result(ok=True, rows_written=len(out_rows) - 1, message=msg, extra={"games": preview_games[:50]})
        return 0
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        emit_result(ok=False, rows_written=0, error=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
