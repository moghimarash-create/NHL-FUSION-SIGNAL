import { useState, useEffect, Component, type ErrorInfo, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Layers, ExternalLink, ChevronDown, ChevronUp, Database, ShieldCheck } from "lucide-react";
import NbaDashboardTab, { type FusionModeKey, type TwinDbKind } from "./NbaDashboardTab";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

const ENV_INPUT_SHEET_ID = String(import.meta.env.VITE_NHL_FUSION_INPUT_SHEET_ID || "").trim();
const ENV_CALC_SHEET_ID = String(import.meta.env.VITE_NHL_FUSION_CALC_SHEET_ID || "").trim();

const MODE_KEYS: FusionModeKey[] = [
  "tri_gf_ultralock",
  "anti_nobet_smart",
  "total_elem_12",
  "tri_gf_routed",
  "gf_fin_pure",
  "pos_inv_lock",
  "earth_neg_lock",
  "safe_dl_core",
  "double_pwr_lock",
  "geo_1xxx_lock",
  "dual_pillar",
  "vip_cross",
  "astro_lock",
  "diamond",
];

type ModeBenchInfo = {
  shortFa: string;
  formulaEn: string;
  holdPct: string;
  holdRec: string;
  s2526: string;
  s2627: string;
  last50: string;
  edge: string;
};

const DEFAULT_FUSION_MODES: Record<FusionModeKey, ModeBenchInfo> = {
  tri_gf_ultralock: {
    shortFa: "حالت ۱۲ (ابرقفل ۳ عددی تلفیقی + قطب سرد ۰xxx + ۲ قفل ایمنی v68): پیش‌فرض",
    formulaEn: "Mode_9_Ultra(GF-FIN, Cnt>=1) ∪ ColdAnchor_Keep(0xxx<=-4) ∪ Bipolar_0011(Twin) ∪ S3_SignSplit ∪ Zero1xxx_Opp ∪ EARTH_Flip \\ (DualEarth_Hold ∪ TwinVs3of3_Hold)",
    holdPct: "54.5%",
    holdRec: "146/268",
    s2526: "55.3% (125/226)",
    s2627: "50.0% (21/42)",
    last50: "54.0% (27/50)",
    edge: "All 57.0% (285/500)",
  },
  anti_nobet_smart: {
    shortFa: "حالت ۱۳ (ضد NO-BET هوشمند: حالت ۱۲ + آزادسازی مستقیم گروه ۱ + چرخش عکس گروه ۲)",
    formulaEn: "Mode_12_Core ∪ Direct_Release(M11 & NonEARTH & Log5>=75%) ∪ Opposite_Flip(!M11 & NonEARTH & (DP_Opp | RawFB_OppLog5>=60%))",
    holdPct: "56.5%",
    holdRec: "454/803",
    s2526: "55.3% (352/637)",
    s2627: "61.4% (102/166)",
    last50: "68.0% (34/50)",
    edge: "VIP 58.9% (626/1063)",
  },
  total_elem_12: {
    shortFa: "حالت ۱۴ (قطبیت المنت کل ۱۲ بازیکن+تیم + داور رتبه‌بندی و امتیازدهی وزنی ۶ باکس v82)",
    formulaEn: "13_Entities + DomElem[F,A,W,E] + PureLog5 \\ (2xWATER ∪ Bipolar<75% ∪ AwayWarm<0 -> Flip_Opp) ∪ OppFlip(12P|M11)",
    holdPct: "55.8%",
    holdRec: "309/554",
    s2526: "54.1% (236/436)",
    s2627: "61.9% (73/118)",
    last50: "62.0% (31/50)",
    edge: "VIP 59.5% (515/866)",
  },
  tri_gf_routed: {
    shortFa: "حالت ۱۱ (موتور مستقل ۳ عددی + قطب سرد ۰xxx + ضدحذف): بدون همزاد",
    formulaEn: "3-Num [Σ(1xxx), Σ(0xxx/0011), Σ(8), Σ(GF), Σ(3)] + Anti-Drop: ColdAnchor_Keep ∪ S3_SignSplit ∪ Zero1xxx_Opp ∪ EARTH_Flip ∪ PosInv",
    holdPct: "54.4%",
    holdRec: "514/944",
    s2526: "52.9% (397/751)",
    s2627: "60.6% (117/193)",
    last50: "64.0% (32/50)",
    edge: "VIP 58.9% (657/1116)",
  },
  gf_fin_pure: {
    shortFa: "حالت ۱۰ (موتور خالص GF-FIN): عدد کمتر یا منفی‌تر برنده • بدون قفل و شرط",
    formulaEn: "Pick = argmin(Σ GF-FIN_8_Players) where GF-FIN = (8*s1 + 4*s2 + 2*s3 + 1*s4)/10 • Zero Locks / Zero Filters",
    holdPct: "50.8%",
    holdRec: "887/1745",
    s2526: "50.6% (703/1388)",
    s2627: "51.5% (184/357)",
    last50: "54.0% (27/50)",
    edge: "+0.3pp",
  },
  pos_inv_lock: {
    shortFa: "حالت ۹ (قفل جامع v5 + داور GF-FIN)",
    formulaEn: "Mode_7_GF(Cnt>=1) ∪ VIP_SafeDL ∪ [Both_1xxx>0 -> Polarity_Inversion] ∪ [Div(1xxx,Σ8) & |ΔGF-FIN|>=6 -> 2/3_Referee]",
    holdPct: "52.6%",
    holdRec: "112/213",
    s2526: "52.8% (94/178)",
    s2627: "51.4% (18/35)",
    last50: "56.0% (28/50)",
    edge: "VIP 56.3% (139/247)",
  },
  earth_neg_lock: {
    shortFa: "حالت ۷ (قفل ایمن منفی + داور GF-FIN)",
    formulaEn: "Dual_Pillar & !(EARTH vs Stronger) & !PosInv_Trap & NegAnchor & (Double_Lock | (Cnt>=1 & |ΔGF-FIN|>=6 & 2/3_Maj))",
    holdPct: "62.2%",
    holdRec: "23/37",
    s2526: "55.6% (15/27)",
    s2627: "80.0% (8/10)",
    last50: "62.2% (23/37)",
    edge: "All 64.9% (50/77)",
  },
  safe_dl_core: {
    shortFa: "حالت ۸ (قفل مستقل ایمن + داور GF-FIN)",
    formulaEn: "Mode_7_GF(Cnt>=1) ∪ VIP_SafeDL ∪ ((Safe_DL | (Cnt>=1 & |ΔGF-FIN|>=6 & 2/3_Maj)) & NoEARTH & NegAnchor & Log5>=60% & T=P)",
    holdPct: "51.6%",
    holdRec: "49/95",
    s2526: "48.1% (37/77)",
    s2627: "66.7% (12/18)",
    last50: "64.0% (32/50)",
    edge: "All 56.2% (99/176)",
  },
  double_pwr_lock: {
    shortFa: "حالت ۶ (قفل دوگانه ۱xxx + Σ8): بدون فیلتر لنگر منفی",
    formulaEn: "Dual_Pillar AND Σ Pwr(1xxx, Pick) < Opp AND Σ Pwr(All 8, Pick) < Opp",
    holdPct: "61.5%",
    holdRec: "24/39",
    s2526: "57.1% (16/28)",
    s2627: "72.7% (8/11)",
    last50: "61.5% (24/39)",
    edge: "+2.2pp",
  },
  geo_1xxx_lock: {
    shortFa: "حالت ۵ (فیلتر رمل ۱xxx): تلفیق دو-ستونی + برتری منفی ۱xxx",
    formulaEn: "Dual_Pillar AND Σ Pwr(GEO-FIN = 1xxx, Pick) < Σ Pwr(GEO-FIN = 1xxx, Opp)",
    holdPct: "62.7%",
    holdRec: "37/59",
    s2526: "59.1% (26/44)",
    s2627: "73.3% (11/15)",
    last50: "66.0% (33/50)",
    edge: "+1.4pp",
  },
  dual_pillar: {
    shortFa: "حالت ۱ (جامع): تلفیق دو-ستونی تیم + بازیکن",
    formulaEn: "(T.f1_wtp & (Twin_P == Pick | F30_P > 0)) ∪ (P_C.f1_wtp & (Twin_T == Pick | F30_T > 0))",
    holdPct: "63.3%",
    holdRec: "76/120",
    s2526: "64.5% (60/93)",
    s2627: "59.3% (16/27)",
    last50: "74.0% (37/50)",
    edge: "All 64.3% (157/244)",
  },
  vip_cross: {
    shortFa: "حالت ۲ (شکارچی طلایی): VIP با تأیید متقابل دو موتور",
    formulaEn: "(T.vip & (Twin_P == Pick | F30_P > 0)) ∪ (P_C.vip & (Twin_T == Pick | F30_T > 0))",
    holdPct: "58.5%",
    holdRec: "38/65",
    s2526: "54.2% (26/48)",
    s2627: "70.6% (12/17)",
    last50: "58.0% (29/50)",
    edge: "VIP 81.2% (13/16)",
  },
  astro_lock: {
    shortFa: "حالت ۳ (قفل متقابل نجومی): سیگنال یک موتور + F30 مثبت موتور دوم",
    formulaEn: "(T.f1_wtp & F30_P_for > 0) ∪ (P_C.f1_wtp & F30_T_for > 0)",
    holdPct: "63.5%",
    holdRec: "47/74",
    s2526: "65.0% (39/60)",
    s2627: "57.1% (8/14)",
    last50: "66.0% (33/50)",
    edge: "All 68.2% (105/154)",
  },
  diamond: {
    shortFa: "حالت ۴ (قفل الماس T ∩ P): توافق هم‌زمان سیگنال نهایی دو موتور",
    formulaEn: "T.f1_wtp AND P_C.f1_wtp (DEG1=88 • 28 GEMINI • Dual-Engine Intersection)",
    holdPct: "77.8%",
    holdRec: "7/9",
    s2526: "75.0% (6/8)",
    s2627: "100.0% (1/1)",
    last50: "81.2% (13/16 All)",
    edge: "+10.0pp",
  },
};

function Home() {
  const [fusionMode, setFusionMode] = useState<FusionModeKey>(() => {
    try {
      const s = window.localStorage.getItem("nhl_fusion_mode_v82") as FusionModeKey | null;
      if (s && s in DEFAULT_FUSION_MODES) return s;
    } catch {}
    return "tri_gf_ultralock";
  });
  const [twinDbKind, setTwinDbKind] = useState<TwinDbKind>("team");
  const [openBench, setOpenBench] = useState<boolean>(false);
  const [fusionModes, setFusionModes] = useState<Record<FusionModeKey, ModeBenchInfo>>(DEFAULT_FUSION_MODES);
  const [sheetLinks, setSheetLinks] = useState<{ inputUrl: string; calcUrl: string }>(() => ({
    inputUrl: ENV_INPUT_SHEET_ID ? `https://docs.google.com/spreadsheets/d/${ENV_INPUT_SHEET_ID}/edit` : "",
    calcUrl: ENV_CALC_SHEET_ID ? `https://docs.google.com/spreadsheets/d/${ENV_CALC_SHEET_ID}/edit` : "",
  }));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (const p of ["./fusion-rpc/sheet-links", "./api/sheet-links"]) {
        try {
          const r = await fetch(p);
          if (r.ok) {
            const d = await r.json();
            if (!cancelled && d && typeof d === "object") {
              setSheetLinks((prev) => ({
                inputUrl: d.inputSheetUrl || prev.inputUrl,
                calcUrl: d.calcSheetUrl || prev.calcUrl,
              }));
              break;
            }
          }
        } catch {}
      }
    })();

    (async () => {
      try {
        const r = await fetch("./fusion_modes_summary.json");
        if (!r.ok) return;
        const sum = await r.json();
        if (cancelled || !sum || typeof sum !== "object") return;
        setFusionModes((prev) => {
          const next = { ...prev };
          for (const mk of MODE_KEYS) {
            const row = sum[mk];
            if (!row?.holdout_2527) continue;
            const h = row.holdout_2527;
            const s25 = row.s2526;
            const s26 = row.s2627;
            const l50 = row.last50;
            const edgeNum = typeof h.edge === "number" ? h.edge : 0;
            next[mk] = {
              ...prev[mk],
              holdPct: `${Number(h.pct ?? 0).toFixed(1)}%`,
              holdRec: `${h.w ?? 0}/${h.n ?? 0}`,
              s2526: s25 ? `${Number(s25.pct ?? 0).toFixed(1)}% (${s25.w ?? 0}/${s25.n ?? 0})` : prev[mk].s2526,
              s2627:
                s26 && (s26.n ?? 0) > 0
                  ? `${Number(s26.pct ?? 0).toFixed(1)}% (${s26.w ?? 0}/${s26.n ?? 0})`
                  : prev[mk].s2627,
              last50:
                l50 && (l50.n ?? 0) > 0
                  ? `${Number(l50.pct ?? 0).toFixed(1)}% (${l50.w ?? 0}/${l50.n ?? 0})`
                  : prev[mk].last50,
              edge: edgeNum >= 0 ? `+${edgeNum.toFixed(1)}pp` : prev[mk].edge,
            };
          }
          return next;
        });
      } catch {}
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const switchFusion = (m: FusionModeKey) => {
    setFusionMode(m);
    try {
      window.localStorage.setItem("nhl_fusion_mode_v82", m);
    } catch {}
  };

  const cur = fusionModes[fusionMode];

  return (
    <div className="min-h-[100dvh] w-full bg-background flex flex-col font-sans">
      <div className="flex-1 w-full max-w-6xl mx-auto px-3.5 sm:px-4 py-5 md:py-7 flex flex-col">
        <header className="mb-3.5 flex flex-wrap items-center justify-between gap-3" dir="rtl">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-lg bg-emerald-700 text-white flex items-center justify-center shadow-xs shrink-0">
              <Layers className="h-4 w-4" />
            </div>
            <div>
              <h1
                className="text-lg md:text-xl font-extrabold tracking-tight text-slate-900"
                data-testid="text-dashboard-title"
              >
                داشبورد مستقل موتور تلفیقی NHL-FUSION-SIGNAL (داور رتبه‌بندی و امتیازدهی وزنی ۶ باکس • v82)
              </h1>
              <p className="text-slate-600 text-xs leading-snug">
                DEG1=88 (28 GEMINI) • KXNHLGAME • باکس ۱: چک‌لیست تیک‌دار شاخص‌های هر دو تیم • باکس ۲: حکم نهایی، قفل استفاده‌شده و نتیجه بازی
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2" dir="rtl">
            {sheetLinks.inputUrl ? (
              <a
                href={sheetLinks.inputUrl}
                target="_blank"
                rel="noreferrer"
                data-testid="link-fusion-sheet-input"
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-extrabold shadow-xs transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                شیت ورودی (NHL-FUSION-INPUT)
              </a>
            ) : null}
            {sheetLinks.calcUrl ? (
              <a
                href={sheetLinks.calcUrl}
                target="_blank"
                rel="noreferrer"
                data-testid="link-fusion-sheet-calc"
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white hover:bg-sky-50 text-sky-950 border border-sky-300 text-xs font-extrabold shadow-2xs transition-colors"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                شیت محاسبات (NHL-FUSION-CALCULATION)
              </a>
            ) : null}
            {!sheetLinks.inputUrl && !sheetLinks.calcUrl && (
              <span
                data-testid="badge-local-safe-sheets"
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-50 text-emerald-900 border border-emerald-300 text-xs font-extrabold"
                title="برای اتصال شیت اختصاصی NHL، متغیرهای NHL_FUSION_INPUT_SHEET_ID و NHL_FUSION_CALC_SHEET_ID را در .env تنظیم کنید"
              >
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" />
                حالت ایمن محلی JSON • بدون اتصال به شیت NBA
              </span>
            )}
          </div>
        </header>

        {/* Clean Single-Row Active Fusion Mode Selector + Collapsible Benchmark/All-Modes Dropdown */}
        <div
          dir="rtl"
          className="mb-4 rounded-xl border-2 border-sky-300 bg-sky-50/90 p-2.5 shadow-2xs space-y-2.5"
          data-testid="bar-fusion-modes"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 flex-1 min-w-[240px]">
              <span className="px-2 py-1 rounded-md bg-emerald-800 text-white text-[11px] font-extrabold shrink-0">
                موتور فعال:
              </span>
              <select
                value={fusionMode}
                onChange={(e) => switchFusion(e.target.value as FusionModeKey)}
                data-testid="select-fusion-mode"
                className="h-8 rounded-lg border-2 border-emerald-600 bg-white px-2.5 text-xs font-extrabold text-slate-950 shadow-2xs max-w-full"
              >
                {MODE_KEYS.map((mk) => (
                  <option key={mk} value={mk}>
                    {fusionMode === mk ? `✓ ${fusionModes[mk].shortFa}` : fusionModes[mk].shortFa}
                  </option>
                ))}
              </select>
              <span className="px-2 py-1 rounded-md bg-emerald-100 text-emerald-950 border border-emerald-300 font-mono text-[11px] font-extrabold">
                برون‌نمونه: {cur.holdPct} ({cur.holdRec}) • فصل جاری: {cur.s2627} • ۵۰ اخیر: {cur.last50}
              </span>
            </div>

            <button
              type="button"
              data-testid="button-toggle-bench"
              onClick={() => setOpenBench((v) => !v)}
              className="px-3 py-1.5 rounded-lg bg-white hover:bg-sky-100 border border-sky-300 text-sky-950 text-xs font-extrabold inline-flex items-center gap-1.5 shadow-2xs"
            >
              {openBench ? "بستن جدول ۱۴ حالت و راهنمای قفل‌ها" : "جدول بنچمارک ۱۴ حالت و راهنمای قفل‌ها"}
              {openBench ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {openBench && (
            <div className="bg-white rounded-lg border border-sky-200 p-3 space-y-3 overflow-x-auto">
              <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-sky-100">
                <div className="flex flex-wrap items-center gap-1.5">
                  {MODE_KEYS.map((mk) => {
                    const m = fusionModes[mk];
                    const active = fusionMode === mk;
                    return (
                      <button
                        key={mk}
                        type="button"
                        data-testid={`tab-fusion-${mk}`}
                        onClick={() => switchFusion(mk)}
                        className={`px-2.5 py-1.5 rounded-md text-[11px] font-extrabold transition-all ${
                          active
                            ? "bg-emerald-800 text-white shadow-xs ring-2 ring-amber-400"
                            : "bg-sky-50 text-sky-950 hover:bg-sky-100 border border-sky-200"
                        }`}
                      >
                        {m.shortFa}
                      </button>
                    );
                  })}
                </div>

                <div className="inline-flex items-center rounded-lg border border-sky-300 bg-sky-50/70 p-0.5 text-[11px] font-bold">
                  <span className="px-2 text-slate-600 inline-flex items-center gap-1">
                    <Database className="h-3 w-3 text-sky-700" />
                    همزادیاب دستی:
                  </span>
                  <button
                    type="button"
                    data-testid="btn-twindb-team"
                    onClick={() => setTwinDbKind("team")}
                    className={`px-2 py-1 rounded-md transition-colors ${
                      twinDbKind === "team" ? "bg-sky-700 text-white" : "text-sky-900 hover:bg-white"
                    }`}
                  >
                    تیم+استادیوم (DEG1=88)
                  </button>
                  <button
                    type="button"
                    data-testid="btn-twindb-player"
                    onClick={() => setTwinDbKind("player")}
                    className={`px-2 py-1 rounded-md transition-colors ${
                      twinDbKind === "player" ? "bg-indigo-700 text-white" : "text-indigo-900 hover:bg-white"
                    }`}
                  >
                    ۸ بازیکن+TOI+شماره
                  </button>
                </div>
              </div>

              {fusionMode === "total_elem_12" && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50/70 p-2.5 text-xs text-slate-800 leading-relaxed">
                  <div className="font-extrabold text-indigo-950 mb-1">
                    معماری خالص حالت ۱۴ در v82 (المنت غالب [F-A-W-E] + ۱۲ بازیکن TOI و تیم با DEG1=88 + داور وزنی ۶ باکس):
                  </div>
                  <div>
                    ۱) <b>حذف عنصر ساختگی جدول (تله EARTH)</b> در حالت ۱۴ و جایگزینی با <b>احتمال برد خالص Log5%</b> • ۲) <b>المنت غالب مجموع المنت‌ها [F-A-W-E]</b>: بیشترین عدد در بردار نهایی ۱۲ بازیکن + تیم + تاریخ؛ شناسایی <b>تله دوقلوی آب (۲×WATER)</b> با تیک قرمز ✕، تایید <b>برتری ۳/۴ عناصر</b> (VIP ★) و شکاف <b>WATER/AIR برابر EARTH</b> • ۳) <b>فیلتر ۳ تله خطا + قانون تیم عکس فاقد شرایط</b> (۱۲ بازیکن خالص / قفل ۱۱ / توان ۱۳).
                  </div>
                </div>
              )}
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-2.5 text-xs text-slate-800 leading-relaxed">
                <div className="font-extrabold text-emerald-950 mb-1">
                  منطق ۶ شاخص باکس ۱ در حالت ۱۲ (ابرقفل ۳ عددی تلفیقی + قطب سرد ۰xxx + ۲ قفل ایمنی v68):
                </div>
                <div>
                  ۱) <b>قطب گرم Σ(1xxx)</b> (منفی‌تر برنده؛ بررسی تله دو-مثبت و حبس ۱xxx=0) • ۲) <b>مجموع ۸ بازیکن Σ(8) با وزن TOI</b> • ۳) <b>داور GF-FIN و Σ(3)</b> (اکثریت ۲/۳ و ۳/۳) • ۴) <b>قطب سرد Σ(0xxx) / 0011</b> • ۵) <b>موتور تلفیقی همزاد NHL (T+P • DEG1=88)</b> • ۶) <b>عنصر جدول و Log5</b> (عبور FIRE/AIR/WATER و شناسایی تله EARTH) + <b>۲ قفل ایمنی v68</b> (توقف نبرد دو تیم EARTH و مهار همزاد برابر توافق ۳/۳ اعداد).
                </div>
              </div>

              <div className="text-xs font-extrabold text-sky-950 flex flex-wrap items-center justify-between gap-2">
                <span>مقایسه برون‌نمونه‌ای بدون آینده‌نگری (r.d &lt; g.d) روی ۳٬۱۵۰ بازی پایان یافته NHL (۲۰۲۴–۲۰۲۷):</span>
                <span className="font-mono text-[11px] text-emerald-950 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded" dir="ltr">
                  {cur.formulaEn}
                </span>
              </div>
              <table className="w-full text-xs border-collapse font-mono tabular-nums text-right">
                <thead>
                  <tr className="bg-sky-100/80 text-sky-950 border-b border-sky-200 font-sans">
                    <th className="py-1.5 px-2.5">معماری موتور تلفیقی (قابل انتخاب آنی)</th>
                    <th className="py-1.5 px-2.5">آزمون برون‌نمونه ۲۰۲۵–۲۷</th>
                    <th className="py-1.5 px-2.5">فصل ۲۰۲۵–۲۶</th>
                    <th className="py-1.5 px-2.5">فصل جاری ۲۰۲۶–۲۷</th>
                    <th className="py-1.5 px-2.5">۵۰ سیگنال اخیر</th>
                    <th className="py-1.5 px-2.5">حاشیه برتری / VIP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-sky-100">
                  {MODE_KEYS.map((mk) => {
                    const m = fusionModes[mk];
                    const isCur = fusionMode === mk;
                    return (
                      <tr
                        key={mk}
                        onClick={() => switchFusion(mk)}
                        className={`cursor-pointer transition-colors ${
                          isCur ? "bg-emerald-50/90 font-bold text-slate-950" : "hover:bg-sky-50/60 text-slate-700"
                        }`}
                      >
                        <td className="py-1.5 px-2.5 font-sans font-extrabold text-sky-950">
                          {isCur ? "✓ " : ""}{m.shortFa}
                        </td>
                        <td className="py-1.5 px-2.5 text-emerald-800 font-extrabold">{m.holdPct} ({m.holdRec})</td>
                        <td className="py-1.5 px-2.5">{m.s2526}</td>
                        <td className="py-1.5 px-2.5 text-indigo-800 font-extrabold">{m.s2627}</td>
                        <td className="py-1.5 px-2.5 text-sky-900 font-extrabold">{m.last50}</td>
                        <td className="py-1.5 px-2.5 text-emerald-700 font-bold" dir="ltr">{m.edge}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <NbaDashboardTab fusionMode={fusionMode} twinDbKind={twinDbKind} />

        <footer className="mt-8 pt-4 border-t border-border/50 text-center">
          <p className="text-xs text-muted-foreground font-mono uppercase tracking-widest">
            NHL-FUSION-SIGNAL v82 • Dual-Engine Fusion Dashboard (Ranked Weighted 6-Box Referee • DEG1=88 • 28 GEMINI • KXNHLGAME)
          </p>
        </footer>
      </div>
    </div>
  );
}

class DashboardErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard ErrorBoundary caught:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div dir="rtl" className="min-h-screen bg-slate-50 p-6 flex items-center justify-center font-sans">
          <div className="max-w-xl w-full rounded-xl border-2 border-red-300 bg-white p-5 shadow-sm space-y-3">
            <h2 className="text-base font-extrabold text-red-700">خطای زمان اجرا در داشبورد</h2>
            <p className="text-xs text-slate-700 font-mono bg-red-50 p-2.5 rounded border border-red-200" dir="ltr">
              {this.state.error.message}
            </p>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="px-3 py-1.5 rounded-lg bg-emerald-700 text-white text-xs font-bold"
            >
              تلاش مجدد
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  return (
    <DashboardErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <Home />
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </DashboardErrorBoundary>
  );
}

export default App;
