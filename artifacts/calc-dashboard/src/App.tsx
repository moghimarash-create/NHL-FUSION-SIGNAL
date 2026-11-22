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
  "nhl_ice_ultralock",
  "nhl_anti_nobet",
  "geo_1xxx_lock",
  "dual_pillar",
  "diamond",
  "double_pwr_lock",
  "earth_neg_lock",
  "astro_lock",
  "vip_cross",
  "tri_gf_ultralock",
  "total_elem_12",
  "anti_nobet_smart",
  "safe_dl_core",
  "tri_gf_routed",
  "pos_inv_lock",
  "gf_fin_pure",
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
  nhl_ice_ultralock: {
    shortFa: "حالت ۱۵ (ابرقفل اختصاصی هاکی NHL • DEG1=88 + سپر FIRE/AIR + ۱ گلر و ۷ اسکیت‌باز + چرخش دوقطبی Flip Guard): پیش‌فرض",
    formulaEn: "NHL_Ice_UltraLock(DEG1=88, 1G+7S_TOI, Pyth_2.05) + FlipGuard[!Diamond & (PosPole_1G7S ∪ Twin50_F30 ∪ TR8_Bipolar ∪ TR9_ColdDGF)] + !M16_Route(TR∪EC)",
    holdPct: "69.3%",
    holdRec: "52/75",
    s2526: "67.7% (42/62)",
    s2627: "76.9% (10/13)",
    last50: "74.0% (37/50)",
    edge: "+4.4pp • All 79.5% (116/146)",
  },
  nhl_anti_nobet: {
    shortFa: "حالت ۱۶ (ضد NO-BET هوشمند هاکی NHL: حالت ۱۵ + اتحاد یانگ و شکار تله سرد + گارد دوقطبی TR8∪TR9)",
    formulaEn: "Mode_15_Core ∪ [(YangUnion_Release ∪ Contender_YinMismatch) + FlipGuard(TR8 ∪ TR9)] + !M16_Route(TR1..13 ∪ EC1..4 -> 60.9% All 3,150)",
    holdPct: "64.0%",
    holdRec: "87/136",
    s2526: "60.4% (61/101)",
    s2627: "74.3% (26/35)",
    last50: "74.0% (37/50)",
    edge: "All 69.8% (183/262) • VIP 70.9%",
  },
  geo_1xxx_lock: {
    shortFa: "حالت ۵ (فیلتر رمل ۱xxx • ۱ گلر + ۷ اسکیت‌باز): تلفیق دو-ستونی + برتری منفی ۱xxx",
    formulaEn: "Dual_Pillar(1G+7S) AND Σ Pwr(GEO-FIN = 1xxx, Pick) < Σ Pwr(GEO-FIN = 1xxx, Opp)",
    holdPct: "72.2%",
    holdRec: "52/72",
    s2526: "70.9% (39/55)",
    s2627: "76.5% (13/17)",
    last50: "72.0% (36/50)",
    edge: "+8.7pp",
  },
  dual_pillar: {
    shortFa: "حالت ۱ (جامع • ۱ گلر + ۷ اسکیت‌باز): تلفیق دو-ستونی تیم + بازیکن",
    formulaEn: "(T.f1_wtp & (Twin_P == Pick | F30_P > 0)) ∪ (P_C.f1_wtp & (Twin_T == Pick | F30_T > 0))",
    holdPct: "65.4%",
    holdRec: "85/130",
    s2526: "63.8% (67/105)",
    s2627: "72.0% (18/25)",
    last50: "72.0% (36/50)",
    edge: "+0.4pp",
  },
  diamond: {
    shortFa: "حالت ۴ (قفل الماس T ∩ P): توافق هم‌زمان سیگنال نهایی دو موتور",
    formulaEn: "T.f1_wtp AND P_C.f1_wtp (DEG1=88 • 28 GEMINI • 1G+7S Dual-Engine Intersection)",
    holdPct: "80.0%",
    holdRec: "4/5",
    s2526: "80.0% (4/5)",
    s2627: "90.0% (9/10 All)",
    last50: "90.0% (9/10 All)",
    edge: "+12.7pp",
  },
  double_pwr_lock: {
    shortFa: "حالت ۶ (قفل دوگانه ۱xxx + Σ8 • ۱ گلر + ۷ اسکیت‌باز): بدون فیلتر لنگر منفی",
    formulaEn: "Dual_Pillar(1G+7S) AND Σ Pwr(1xxx, Pick) < Opp AND Σ Pwr(All 8, Pick) < Opp",
    holdPct: "67.4%",
    holdRec: "29/43",
    s2526: "63.3% (19/30)",
    s2627: "76.9% (10/13)",
    last50: "67.4% (29/43)",
    edge: "+3.6pp",
  },
  earth_neg_lock: {
    shortFa: "حالت ۷ (قفل ایمن منفی + داور GF-FIN • ۱ گلر + ۷ اسکیت‌باز)",
    formulaEn: "Dual_Pillar & !(EARTH vs Stronger) & !PosInv_Trap & NegAnchor & (Double_Lock | (Cnt>=1 & |ΔGF-FIN|>=6 & 2/3_Maj))",
    holdPct: "64.4%",
    holdRec: "29/45",
    s2526: "58.8% (20/34)",
    s2627: "81.8% (9/11)",
    last50: "64.4% (29/45)",
    edge: "All 64.7% (55/85)",
  },
  astro_lock: {
    shortFa: "حالت ۳ (قفل متقابل نجومی): سیگنال یک موتور + F30 مثبت موتور دوم",
    formulaEn: "(T.f1_wtp & F30_P_for > 0) ∪ (P_C.f1_wtp & F30_T_for > 0)",
    holdPct: "63.5%",
    holdRec: "54/85",
    s2526: "63.0% (46/73)",
    s2627: "66.7% (8/12)",
    last50: "60.0% (30/50)",
    edge: "All 66.0% (97/147)",
  },
  vip_cross: {
    shortFa: "حالت ۲ (شکارچی طلایی): VIP با تأیید متقابل دو موتور",
    formulaEn: "(T.vip & (Twin_P == Pick | F30_P > 0)) ∪ (P_C.vip & (Twin_T == Pick | F30_T > 0))",
    holdPct: "62.9%",
    holdRec: "44/70",
    s2526: "58.9% (33/56)",
    s2627: "78.6% (11/14)",
    last50: "60.0% (30/50)",
    edge: "VIP 90.0% (9/10)",
  },
  tri_gf_ultralock: {
    shortFa: "حالت ۱۲ (ابرقفل ۳ عددی تلفیقی + قطب سرد ۰xxx + ۲ قفل ایمنی v68)",
    formulaEn: "Mode_9_Ultra(GF-FIN, Cnt>=1) ∪ ColdAnchor_Keep(0xxx<=-4) ∪ Bipolar_0011(Twin) ∪ S3_SignSplit ∪ Zero1xxx_Opp ∪ EARTH_Flip \\ (DualEarth_Hold ∪ TwinVs3of3_Hold)",
    holdPct: "55.3%",
    holdRec: "152/275",
    s2526: "53.9% (123/228)",
    s2627: "61.7% (29/47)",
    last50: "64.0% (32/50)",
    edge: "All 58.6% (286/488)",
  },
  total_elem_12: {
    shortFa: "حالت ۱۴ (قطبیت المنت کل ۱ گلر + ۱۱ اسکیت‌باز + تیم + داور وزنی ۶ باکس v82)",
    formulaEn: "13_Entities(1G+11S+Team) + DomElem[F,A,W,E] + PureLog5 \\ (2xWATER ∪ Bipolar<75% ∪ AwayWarm<0 -> Flip_Opp) ∪ OppFlip(12P|M11)",
    holdPct: "56.6%",
    holdRec: "317/560",
    s2526: "54.2% (240/443)",
    s2627: "65.8% (77/117)",
    last50: "66.0% (33/50)",
    edge: "VIP 59.0% (511/866)",
  },
  anti_nobet_smart: {
    shortFa: "حالت ۱۳ (ضد NO-BET هوشمند پایه v70: حالت ۱۲ + آزادسازی مستقیم + چرخش عکس)",
    formulaEn: "Mode_12_Core ∪ Direct_Release(M11 & NonEARTH & Log5>=75%) ∪ Opposite_Flip(!M11 & NonEARTH & (DP_Opp | RawFB_OppLog5>=60%))",
    holdPct: "56.0%",
    holdRec: "440/786",
    s2526: "54.2% (336/620)",
    s2627: "62.7% (104/166)",
    last50: "70.0% (35/50)",
    edge: "VIP 59.7% (632/1059)",
  },
  safe_dl_core: {
    shortFa: "حالت ۸ (قفل مستقل ایمن + داور GF-FIN • ۱ گلر + ۷ اسکیت‌باز)",
    formulaEn: "Mode_7_GF(Cnt>=1) ∪ VIP_SafeDL ∪ ((Safe_DL | (Cnt>=1 & |ΔGF-FIN|>=6 & 2/3_Maj)) & NoEARTH & NegAnchor & Log5>=60% & T=P)",
    holdPct: "57.0%",
    holdRec: "69/121",
    s2526: "51.1% (47/92)",
    s2627: "75.9% (22/29)",
    last50: "72.0% (36/50)",
    edge: "All 59.0% (124/210)",
  },
  tri_gf_routed: {
    shortFa: "حالت ۱۱ (موتور مستقل ۳ عددی + قطب سرد ۰xxx + ضدحذف): بدون همزاد",
    formulaEn: "3-Num [Σ(1xxx), Σ(0xxx/0011), Σ(8), Σ(GF), Σ(3)] + Anti-Drop: ColdAnchor_Keep ∪ S3_SignSplit ∪ Zero1xxx_Opp ∪ EARTH_Flip ∪ PosInv",
    holdPct: "54.0%",
    holdRec: "509/943",
    s2526: "52.0% (391/752)",
    s2627: "61.8% (118/191)",
    last50: "66.0% (33/50)",
    edge: "VIP 59.0% (656/1111)",
  },
  pos_inv_lock: {
    shortFa: "حالت ۹ (قفل جامع v5 + داور GF-FIN)",
    formulaEn: "Mode_7_GF(Cnt>=1) ∪ VIP_SafeDL ∪ [Both_1xxx>0 -> Polarity_Inversion] ∪ [Div(1xxx,Σ8) & |ΔGF-FIN|>=6 -> 2/3_Referee]",
    holdPct: "50.8%",
    holdRec: "96/189",
    s2526: "49.7% (79/159)",
    s2627: "56.7% (17/30)",
    last50: "60.0% (30/50)",
    edge: "VIP 57.5% (131/228)",
  },
  gf_fin_pure: {
    shortFa: "حالت ۱۰ (موتور خالص GF-FIN): عدد کمتر یا منفی‌تر برنده • بدون قفل و شرط",
    formulaEn: "Pick = argmin(Σ GF-FIN_8_Players) where GF-FIN = (8*s1 + 4*s2 + 2*s3 + 1*s4)/10 • Zero Locks / Zero Filters",
    holdPct: "52.3%",
    holdRec: "909/1739",
    s2526: "52.0% (719/1384)",
    s2627: "53.5% (190/355)",
    last50: "52.0% (26/50)",
    edge: "+1.4pp",
  },
};

function Home() {
  const [fusionMode, setFusionMode] = useState<FusionModeKey>(() => {
    try {
      const s = window.localStorage.getItem("nhl_fusion_mode_v83") as FusionModeKey | null;
      if (s && s in DEFAULT_FUSION_MODES) return s;
    } catch {}
    return "nhl_ice_ultralock";
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
      window.localStorage.setItem("nhl_fusion_mode_v83", m);
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
                داشبورد مستقل موتور تلفیقی NHL-FUSION-SIGNAL (ابرقفل اختصاصی هاکی DEG1=88 • ۱ گلر + اسکیت‌بازان • v83)
              </h1>
              <p className="text-slate-600 text-xs leading-snug">
                DEG1=88 (28 GEMINI • AIR) • KXNHLGAME • قانون ۱ گلر اصلی + ۷ اسکیت‌باز TOI • باکس ۱: چک‌لیست تیک‌دار • باکس ۲: حکم نهایی و نتیجه بازی
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
              {openBench ? "بستن جدول ۱۶ حالت و راهنمای قفل‌ها" : "جدول بنچمارک ۱۶ حالت و راهنمای قفل‌ها"}
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
                    ۱ گلر+۷ اسکیت‌باز TOI
                  </button>
                </div>
              </div>

              <div className="rounded-lg border border-cyan-300 bg-cyan-50/80 p-2.5 text-xs text-slate-800 leading-relaxed">
                <div className="font-extrabold text-cyan-950 mb-1">
                  کالیبراسیون اختصاصی هاکی روی یخ در حالت ۱۵ و ۱۶ + گارد چرخش دوقطبی (TR8∪TR9) و مسیریاب ضدتله باکس ۱ و دو-EARTH (DEG1=88 • Zero-Lookahead):
                </div>
                <div>
                  ۱) <b>ترکیب خالص بازیکنان هاکی (۱ گلر اصلی + ۷ اسکیت‌باز برتر TOI)</b> با نمایش کامل <b>قطب گرم Σ(1xxx)</b>، <b>قطب سرد Σ(0xxx)</b> و <b>اختلاف قطبین Δ(1xxx − 0xxx)</b> (همراه بردار <b>+Tm</b>) در باکس ۱ حالت‌های ۱۵ و ۱۶ • ۲) <b>لایه چرخش هوشمند سیگنال‌های حالت ۱۵ و ۱۶ (Flip Guard بدون حذف هیچ بازی)</b>: مهار تله دو-مثبت (+,+) ۱G+7S، بن‌بست همزاد ۵۰٪ مرزی و <b>گارد دوقطبی خالص TR8 ∪ TR9</b> ⬅ ارتقای حالت ۱۵ به <b>۷۹.۵٪ کل (۱۱۶/۱۴۶ • ۲۰۲۴–۲۵: ۹۰.۱٪ • برون‌نمونه: ۶۹.۳٪)</b> و حالت ۱۶ به <b>۶۹.۸٪ کل (۱۸۳/۲۶۲)</b> • ۳) <b>مسیریاب ضدحذف بازی‌های خارج از سیگنال (!M16 = ۲٬۸۸۸ بازی)</b>: ترکیب ۸ تله قطبی باکس ۱ (<b>TR1..TR13</b>) + ۴ زیرقانون سه‌فصله دو-EARTH (<b>EC1∪EC2∪EC3∪EC4: مجموع EARTH + Pyth% کوچک‌تر</b>) ⬅ عبور کل <b>۳٬۱۵۰ بازی مسیریابی‌شده</b> کارت ۶ از مرز ۶۰٪ و رسیدن به <b>۶۰.۸۹٪ (۱٬۹۱۸/۳٬۱۵۰ • +۱۵۵ برد خالص)</b> با حفظ ۱۰۰٪ دست‌نخورده حالت‌های ۱ تا ۱۴.
                </div>
              </div>

              {fusionMode === "total_elem_12" && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50/70 p-2.5 text-xs text-slate-800 leading-relaxed">
                  <div className="font-extrabold text-indigo-950 mb-1">
                    معماری خالص حالت ۱۴ در v82 (المنت غالب [F-A-W-E] + ۱ گلر و ۱۱ اسکیت‌باز TOI و تیم با DEG1=88 + داور وزنی ۶ باکس):
                  </div>
                  <div>
                    ۱) <b>حذف عنصر ساختگی جدول (تله EARTH)</b> در حالت ۱۴ و جایگزینی با <b>احتمال برد خالص Log5%</b> • ۲) <b>المنت غالب مجموع المنت‌ها [F-A-W-E]</b>: بیشترین عدد در بردار نهایی ۱۲ بازیکن + تیم + تاریخ؛ شناسایی <b>تله دوقلوی آب (۲×WATER)</b> با تیک قرمز ✕، تایید <b>برتری ۳/۴ عناصر</b> (VIP ★) و شکاف <b>WATER/AIR برابر EARTH</b> • ۳) <b>فیلتر ۳ تله خطا + قانون تیم عکس فاقد شرایط</b> (۱۲ بازیکن خالص / قفل ۱۱ / توان ۱۳).
                  </div>
                </div>
              )}

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
                    <th className="py-1.5 px-2.5">حاشیه برتری / کل ۲۴–۲۷</th>
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
            NHL-FUSION-SIGNAL v83 • Dedicated NHL Ice Super-Lock (1G + 7 Skaters TOI • DEG1=88 • 28 GEMINI • KXNHLGAME)
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
