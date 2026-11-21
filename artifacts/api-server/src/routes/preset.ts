import { Router, type IRouter } from "express";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { logger } from "../lib/logger";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PYTHON_DIR = path.resolve(__dirname, "..", "python");
const DATA_DIR = path.resolve(__dirname, "../../data");
const PRESET_FILE = path.join(DATA_DIR, "schedule_sync_state.json");
const SCRIPT = path.join(PYTHON_DIR, "step1_apply_preset.py");

export type ScheduleGamePreview = {
  date: string;
  weekday: string;
  time: string;
  homeTeam: string;
  awayTeam: string;
  deg1: number;
  homeDeg2: string;
  awayDeg2: string;
  arenaDeg3: string;
  arena: string;
  tz: string;
  lat: string;
  lon: string;
  season: string;
  gameType: string;
  homeScore: string;
  awayScore: string;
  winner: string;
};

export type ScheduleSyncState = {
  startDate: string;
  endDate: string;
  utcControl: boolean;
  deg1: number;
  deg2Mode?: "full" | "code";
  appliedAt: string | null;
  rowsWritten: number | null;
  message: string | null;
  games: ScheduleGamePreview[];
};

export const DEFAULT_SYNC: ScheduleSyncState = {
  startDate: "2026-11-20",
  endDate: "2026-11-21",
  utcControl: false,
  deg1: 88,
  deg2Mode: "full",
  appliedAt: null,
  rowsWritten: 16,
  message: "Loaded scheduled NHL games (DEG1=88) from NHL_SCHEDULE_2025_2027",
  games: [],
};

const router: IRouter = Router();

router.get("/sheet-links", (_req, res): void => {
  const inId = (process.env.NHL_FUSION_INPUT_SHEET_ID ?? "").trim();
  const calcId = (process.env.NHL_FUSION_CALC_SHEET_ID ?? "").trim();
  res.json({
    ok: true,
    inputSheetId: inId,
    calcSheetId: calcId,
    inputSheetUrl: inId ? `https://docs.google.com/spreadsheets/d/${inId}/edit` : "",
    calcSheetUrl: calcId ? `https://docs.google.com/spreadsheets/d/${calcId}/edit` : "",
  });
});

async function readState(): Promise<ScheduleSyncState> {
  try {
    const raw = await fs.readFile(PRESET_FILE, "utf-8");
    return { ...DEFAULT_SYNC, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_SYNC };
  }
}

async function writeState(state: ScheduleSyncState): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  const tmp = PRESET_FILE + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(state, null, 2), "utf-8");
  await fs.rename(tmp, PRESET_FILE);
}

function runSyncScript(params: { startDate: string; endDate: string; utcControl: boolean; deg1: number; deg2Mode: "full" | "code" }): Promise<{
  ok: boolean;
  rowsWritten: number | null;
  message: string | null;
  error: string | null;
  games: ScheduleGamePreview[];
  output: string;
}> {
  return new Promise((resolve) => {
    const args = [
      SCRIPT,
      "--start-date",
      params.startDate,
      "--end-date",
      params.endDate,
      "--utc-control",
      params.utcControl ? "1" : "0",
      "--deg1",
      String(params.deg1 || 88),
      "--deg2-mode",
      params.deg2Mode || "full",
    ];
    const child = spawn("python3", args, { env: process.env, cwd: PYTHON_DIR });
    let out = "";
    child.stdout.on("data", (d: Buffer) => (out += d.toString()));
    child.stderr.on("data", (d: Buffer) => (out += d.toString()));
    child.on("error", (err) =>
      resolve({ ok: false, rowsWritten: null, message: null, error: `Failed to start python3: ${err.message}`, games: [], output: out }),
    );
    child.on("close", (code) => {
      let parsed: {
        ok?: boolean;
        rowsWritten?: number | null;
        message?: string | null;
        error?: string | null;
        games?: ScheduleGamePreview[];
      } | null = null;
      for (const line of out.split(/\r?\n/).reverse()) {
        if (line.startsWith("__RESULT__ ")) {
          try {
            parsed = JSON.parse(line.slice("__RESULT__ ".length));
          } catch {
            /* ignore */
          }
          break;
        }
      }
      const ok = (code ?? -1) === 0 && !!parsed?.ok;
      resolve({
        ok,
        rowsWritten: parsed?.rowsWritten ?? null,
        message: parsed?.message ?? null,
        error: ok ? null : parsed?.error ?? `python3 exited with code ${code}`,
        games: parsed?.games ?? [],
        output: out,
      });
    });
  });
}

let applying = false;

router.get("/preset", async (_req, res): Promise<void> => {
  res.json({ current: await readState(), defaults: DEFAULT_SYNC });
});

router.post("/preset/apply", async (req, res): Promise<void> => {
  const b = (req.body ?? {}) as Record<string, unknown>;
  const startDate = String(b.startDate ?? "2026-11-20").trim();
  const endDate = String(b.endDate ?? startDate).trim();
  const utcControl = Boolean(b.utcControl);
  const deg1 = Number(b.deg1 ?? 88) || 88;
  const deg2Mode: "full" | "code" = b.deg2Mode === "code" ? "code" : "full";

  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate)) {
    res.status(400).json({ error: "startDate and endDate must be YYYY-MM-DD (between 2024-10-04 and 2027-04-11)" });
    return;
  }
  if (applying) {
    res.status(409).json({ error: "A schedule sync is already in progress" });
    return;
  }
  applying = true;
  try {
    const result = await runSyncScript({ startDate, endDate, utcControl, deg1, deg2Mode });
    const prev = await readState();
    const state: ScheduleSyncState = {
      startDate,
      endDate,
      utcControl,
      deg1,
      deg2Mode,
      appliedAt: result.ok ? new Date().toISOString() : prev.appliedAt,
      rowsWritten: result.rowsWritten,
      message: result.ok ? result.message : result.error,
      games: result.ok ? result.games : prev.games,
    };
    if (result.ok) await writeState(state);
    else logger.error({ output: result.output.slice(-2000) }, "Schedule sync failed");
    res.status(result.ok ? 200 : 500).json({
      ok: result.ok,
      current: state,
      error: result.error,
      log: result.output.split(/\r?\n/).filter(Boolean).slice(-40),
    });
  } finally {
    applying = false;
  }
});

async function resolveNhlPublicFile(filename: string): Promise<string> {
  const candidates = [
    path.resolve(__dirname, "../../calc-dashboard/public", filename),
    path.resolve(__dirname, "../../../calc-dashboard/public", filename),
    path.join(DATA_DIR, filename),
  ];
  for (const p of candidates) {
    try {
      await fs.access(p);
      return p;
    } catch {}
  }
  return candidates[0];
}

router.get("/predictions", async (_req, res): Promise<void> => {
  try {
    const file = await resolveNhlPublicFile("nhl_predictions_2024_2027.json");
    const raw = await fs.readFile(file, "utf-8");
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.send(raw);
  } catch (e) {
    res.status(500).json({ error: (e as Error).message, games: [] });
  }
});

// ---------------------------------------------------------------------------
// KALSHI NHL MONEYLINE (KXNHLGAME) AUTO-BETTING & LIVE MARKET ENGINE
// Safe DRY_RUN=true default fallback unless server env keys are configured
// ---------------------------------------------------------------------------

const KALSHI_STATE_FILE = path.join(DATA_DIR, "kalshi_nhl_state.json");

export type KalshiCardOrderPlan = {
  gameNo: number;
  date: string;
  homeTeam: string;
  awayTeam: string;
  winnerTeam: string;
  winnerCode: string;
  ticker: string;
  enabled: boolean;
  stakeUsd: number;
  limitCents: number;
  contracts: number;
};

export type KalshiLedgerEntry = {
  orderId: string;
  ticker: string;
  date: string;
  winnerTeam: string;
  contracts: number;
  limitCents: number;
  estCostUsd: number;
  status: string;
  executedAt: string;
};

export type KalshiServerState = {
  keyId: string;
  privateKeyPem: string;
  env: "live" | "demo";
  defaultStakeUsd: number;
  vipStakeUsd: number;
  autoScheduleEnabled: boolean;
  autoScheduleTimeEt: string;
  savedPlans: Record<string, { updatedAt: string; orders: KalshiCardOrderPlan[] }>;
  ledger: Record<string, KalshiLedgerEntry>;
};

const SERVER_ENV_KEY_ID = (process.env.KALSHI_API_KEY_ID ?? "").trim();
const SERVER_ENV_PRIV_KEY = (process.env.KALSHI_PRIVATE_KEY ?? "").trim();
const HAS_SERVER_ENV_KEYS = Boolean(SERVER_ENV_KEY_ID && SERVER_ENV_PRIV_KEY);
const RAW_DRY_RUN_ENV = (process.env.DRY_RUN ?? "").trim().toLowerCase();
// Safe DRY_RUN=true default unless server env keys are set (and DRY_RUN is not explicitly "true"/"1")
const KALSHI_DRY_RUN_ONLY =
  !HAS_SERVER_ENV_KEYS ||
  RAW_DRY_RUN_ENV === "true" ||
  RAW_DRY_RUN_ENV === "1" ||
  process.env.KALSHI_ENABLED === "0" && !HAS_SERVER_ENV_KEYS;

const DEFAULT_KALSHI_STATE: KalshiServerState = {
  keyId: SERVER_ENV_KEY_ID,
  privateKeyPem: SERVER_ENV_PRIV_KEY,
  env: "live",
  defaultStakeUsd: 3,
  vipStakeUsd: 6,
  autoScheduleEnabled: false,
  autoScheduleTimeEt: "11:00",
  savedPlans: {},
  ledger: {},
};

async function readKalshiState(): Promise<KalshiServerState> {
  try {
    const raw = await fs.readFile(KALSHI_STATE_FILE, "utf-8");
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_KALSHI_STATE,
      ...parsed,
      keyId: SERVER_ENV_KEY_ID || parsed.keyId || "",
      privateKeyPem: SERVER_ENV_PRIV_KEY || parsed.privateKeyPem || "",
      savedPlans: parsed.savedPlans ?? {},
      ledger: parsed.ledger ?? {},
    };
  } catch {
    return { ...DEFAULT_KALSHI_STATE };
  }
}

async function writeKalshiState(st: KalshiServerState): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  const tmp = KALSHI_STATE_FILE + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(st, null, 2), "utf-8");
  await fs.rename(tmp, KALSHI_STATE_FILE);
}

function normalizePrivateKey(rawPem: string): string {
  const s = rawPem.trim().replace(/\\n/g, "\n");
  const isPkcs8 = s.includes("BEGIN PRIVATE KEY");
  const body = s
    .replace(/-----BEGIN [A-Z ]+-----/g, "")
    .replace(/-----END [A-Z ]+-----/g, "")
    .replace(/\s+/g, "");
  const lines = body.match(/.{1,64}/g) ?? [body];
  const tag = isPkcs8 ? "PRIVATE KEY" : "RSA PRIVATE KEY";
  return `-----BEGIN ${tag}-----\n${lines.join("\n")}\n-----END ${tag}-----`;
}

function signKalshiRequest(privateKeyPem: string, timestampMs: string, method: string, pathWithoutQuery: string): string {
  const msg = `${timestampMs}${method.toUpperCase()}${pathWithoutQuery}`;
  const pem = normalizePrivateKey(privateKeyPem);
  const sig = crypto.sign("sha256", Buffer.from(msg, "utf-8"), {
    key: pem,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
  });
  return sig.toString("base64");
}

function getKalshiBaseUrl(env: "live" | "demo"): string {
  return env === "demo" ? "https://demo-api.kalshi.co" : "https://api.elections.kalshi.com";
}

let nhlMarketCache: { fetchedAt: number; byTicker: Record<string, any> } = { fetchedAt: 0, byTicker: {} };

async function loadLocalCachedKalshiNhlMarkets(): Promise<Record<string, any>> {
  const candidates = [
    path.resolve(__dirname, "../../calc-dashboard/public/kalshi_nhl_markets.json"),
    path.resolve(__dirname, "../../../calc-dashboard/public/kalshi_nhl_markets.json"),
  ];
  for (const p of candidates) {
    try {
      const raw = await fs.readFile(p, "utf-8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.markets === "object") {
        return parsed.markets;
      }
    } catch {}
  }
  return {};
}

async function fetchOpenKalshiNhlMarkets(force = false): Promise<Record<string, any>> {
  const now = Date.now();
  if (!force && now - nhlMarketCache.fetchedAt < 20000 && Object.keys(nhlMarketCache.byTicker).length > 0) {
    return nhlMarketCache.byTicker;
  }
  try {
    const url = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNHLGAME&status=open&limit=200";
    const resp = await fetch(url, { headers: { "User-Agent": "NHL-Fusion-Signal/82.0" } });
    if (!resp.ok) {
      if (Object.keys(nhlMarketCache.byTicker).length === 0) {
        nhlMarketCache = { fetchedAt: now, byTicker: await loadLocalCachedKalshiNhlMarkets() };
      }
      return nhlMarketCache.byTicker;
    }
    const data = (await resp.json()) as { markets?: any[] };
    const map: Record<string, any> = {};
    for (const m of data.markets ?? []) {
      const yesAsk = Number(m.yes_ask_dollars ?? (m.yes_ask ? m.yes_ask / 100 : 0));
      const yesBid = Number(m.yes_bid_dollars ?? (m.yes_bid ? m.yes_bid / 100 : 0));
      const lastPrice = Number(m.last_price_dollars ?? (m.last_price ? m.last_price / 100 : 0));
      map[m.ticker] = {
        ticker: m.ticker,
        eventTicker: m.event_ticker,
        title: m.title,
        yesSubTitle: m.yes_sub_title,
        yesAsk,
        yesBid,
        lastPrice,
        yesAskCents: Math.round(yesAsk * 100),
        yesBidCents: Math.round(yesBid * 100),
        volume: m.volume_fp ?? m.volume ?? 0,
        status: m.status,
      };
    }
    if (Object.keys(map).length === 0) {
      const cached = await loadLocalCachedKalshiNhlMarkets();
      nhlMarketCache = { fetchedAt: now, byTicker: cached };
      return cached;
    }
    nhlMarketCache = { fetchedAt: now, byTicker: map };
    return map;
  } catch {
    if (Object.keys(nhlMarketCache.byTicker).length === 0) {
      nhlMarketCache = { fetchedAt: now, byTicker: await loadLocalCachedKalshiNhlMarkets() };
    }
    return nhlMarketCache.byTicker;
  }
}

router.get("/kalshi/nhl-markets", async (req, res): Promise<void> => {
  const force = req.query.force === "1";
  const markets = await fetchOpenKalshiNhlMarkets(force);
  res.json({ ok: true, dryRun: KALSHI_DRY_RUN_ONLY, series: "KXNHLGAME", count: Object.keys(markets).length, markets });
});

router.get("/kalshi/markets", async (req, res): Promise<void> => {
  const force = req.query.force === "1";
  const markets = await fetchOpenKalshiNhlMarkets(force);
  res.json({ ok: true, dryRun: KALSHI_DRY_RUN_ONLY, series: "KXNHLGAME", count: Object.keys(markets).length, markets });
});

router.get("/kalshi/state", async (_req, res): Promise<void> => {
  const st = await readKalshiState();
  const isMock = KALSHI_DRY_RUN_ONLY || !Boolean(st.keyId && st.privateKeyPem);
  res.json({
    ok: true,
    mock: isMock,
    dryRun: isMock,
    series: "KXNHLGAME",
    hasKey: !isMock,
    keyIdMasked: isMock ? "DRY-RUN-SAFE" : `${st.keyId.slice(0, 6)}...${st.keyId.slice(-4)}`,
    env: st.env,
    defaultStakeUsd: st.defaultStakeUsd,
    vipStakeUsd: st.vipStakeUsd,
    autoScheduleEnabled: isMock ? false : st.autoScheduleEnabled,
    autoScheduleTimeEt: st.autoScheduleTimeEt,
    savedPlans: st.savedPlans,
    ledger: st.ledger,
  });
});

router.post("/kalshi/config", async (req, res): Promise<void> => {
  const b = (req.body ?? {}) as Record<string, any>;
  const st = await readKalshiState();
  if (typeof b.keyId === "string" && b.keyId.trim() !== "") st.keyId = b.keyId.trim();
  if (typeof b.privateKeyPem === "string" && b.privateKeyPem.trim() !== "") st.privateKeyPem = b.privateKeyPem.trim();
  if (b.env === "live" || b.env === "demo") st.env = b.env;
  if (typeof b.defaultStakeUsd === "number" && b.defaultStakeUsd > 0) st.defaultStakeUsd = b.defaultStakeUsd;
  if (typeof b.vipStakeUsd === "number" && b.vipStakeUsd > 0) st.vipStakeUsd = b.vipStakeUsd;
  if (typeof b.autoScheduleEnabled === "boolean") st.autoScheduleEnabled = b.autoScheduleEnabled;
  if (typeof b.autoScheduleTimeEt === "string" && b.autoScheduleTimeEt.trim() !== "") st.autoScheduleTimeEt = b.autoScheduleTimeEt.trim();
  await writeKalshiState(st);
  const isMock = KALSHI_DRY_RUN_ONLY || !Boolean(st.keyId && st.privateKeyPem);
  res.json({
    ok: true,
    mock: isMock,
    dryRun: isMock,
    hasKey: !isMock,
    keyIdMasked: isMock ? "DRY-RUN-SAFE" : `${st.keyId.slice(0, 6)}...${st.keyId.slice(-4)}`,
    env: st.env,
    defaultStakeUsd: st.defaultStakeUsd,
    vipStakeUsd: st.vipStakeUsd,
    autoScheduleEnabled: isMock ? false : st.autoScheduleEnabled,
    autoScheduleTimeEt: st.autoScheduleTimeEt,
  });
});

router.post("/kalshi/balance", async (_req, res): Promise<void> => {
  const st = await readKalshiState();
  if (KALSHI_DRY_RUN_ONLY || !st.keyId || !st.privateKeyPem) {
    res.json({
      ok: true,
      mock: true,
      dryRun: true,
      balanceUsd: "0.00",
      portfolioValueUsd: "0.00",
      message: "حالت ایمن DRY_RUN فعال است (کلید سرور Kalshi تنظیم نشده است).",
    });
    return;
  }
  try {
    const ts = String(Date.now());
    const apiPath = "/trade-api/v2/portfolio/balance";
    const sig = signKalshiRequest(st.privateKeyPem, ts, "GET", apiPath);
    const resp = await fetch(`${getKalshiBaseUrl(st.env)}${apiPath}`, {
      headers: {
        "KALSHI-ACCESS-KEY": st.keyId,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": sig,
      },
    });
    const text = await resp.text();
    let data: any = {};
    try { data = JSON.parse(text); } catch {}
    if (!resp.ok) {
      res.status(resp.status).json({ ok: false, error: data?.error?.message ?? data?.message ?? `HTTP ${resp.status}: ${text.slice(0, 200)}` });
      return;
    }
    const balCents = Number(data.balance ?? 0);
    const portCents = Number(data.portfolio_value ?? 0);
    res.json({
      ok: true,
      balanceUsd: (balCents / 100).toFixed(2),
      portfolioValueUsd: (portCents / 100).toFixed(2),
      raw: data,
    });
  } catch (e) {
    res.status(500).json({ ok: false, error: (e as Error).message });
  }
});

router.post("/kalshi/save-plan", async (req, res): Promise<void> => {
  const b = (req.body ?? {}) as { date?: string; orders?: KalshiCardOrderPlan[] };
  const date = String(b.date ?? "").trim();
  const orders = Array.isArray(b.orders) ? b.orders : [];
  if (!date) {
    res.status(400).json({ ok: false, error: "date is required" });
    return;
  }
  const st = await readKalshiState();
  st.savedPlans[date] = {
    updatedAt: new Date().toISOString(),
    orders,
  };
  await writeKalshiState(st);
  res.json({
    ok: true,
    date,
    savedCount: orders.filter((o) => o.enabled).length,
    updatedAt: st.savedPlans[date].updatedAt,
  });
});

async function executeKalshiPlanOrders(
  date: string,
  orders: KalshiCardOrderPlan[],
  requestedMode: "dry_run" | "live"
): Promise<{ ok: boolean; mode: string; dryRun?: boolean; results: any[]; summary: any; error?: string }> {
  const st = await readKalshiState();
  const hasLiveKey = !KALSHI_DRY_RUN_ONLY && Boolean(st.keyId && st.privateKeyPem);
  const mode: "dry_run" | "live" = hasLiveKey ? requestedMode : "dry_run";
  const enabledOrders = orders.filter((o) => o.enabled);
  const liveMarkets = await fetchOpenKalshiNhlMarkets(true);

  if (mode === "live") {
    try {
      const bPath = "/trade-api/v2/portfolio/balance";
      const bTs = String(Date.now());
      const bSig = signKalshiRequest(st.privateKeyPem, bTs, "GET", bPath);
      const bRes = await fetch(`${getKalshiBaseUrl(st.env)}${bPath}`, {
        headers: {
          "KALSHI-ACCESS-KEY": st.keyId,
          "KALSHI-ACCESS-TIMESTAMP": bTs,
          "KALSHI-ACCESS-SIGNATURE": bSig,
        },
      });
      if (bRes.ok) {
        const bData: any = await bRes.json();
        const bd: any[] = Array.isArray(bData?.balance_breakdown) ? bData.balance_breakdown : [];
        const s0 = Number(bd.find((x) => x.exchange_index === 0)?.balance ?? 0);
        const s3 = Number(bd.find((x) => x.exchange_index === 3)?.balance ?? 0);
        const neededUsd = enabledOrders.reduce((acc, o) => acc + Number(o.stakeUsd || st.defaultStakeUsd || 3) * 1.06, 0);
        if (s3 < neededUsd && s0 > 0.5) {
          const transferUsd = Math.min(s0, Math.max(neededUsd - s3 + 1.0, s0));
          const amountCenticents = Math.floor(transferUsd * 10000);
          if (amountCenticents > 0) {
            const tPath = "/trade-api/v2/portfolio/intra_exchange_instance_transfer";
            const tTs = String(Date.now());
            const tSig = signKalshiRequest(st.privateKeyPem, tTs, "POST", tPath);
            await fetch(`${getKalshiBaseUrl(st.env)}${tPath}`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "KALSHI-ACCESS-KEY": st.keyId,
                "KALSHI-ACCESS-TIMESTAMP": tTs,
                "KALSHI-ACCESS-SIGNATURE": tSig,
              },
              body: JSON.stringify({
                source: "event_contract",
                destination: "event_contract",
                source_exchange_shard: 0,
                destination_exchange_shard: 3,
                amount: amountCenticents,
              }),
            });
            await new Promise((r) => setTimeout(r, 2500));
          }
        }
      }
    } catch {}
  }

  const results: any[] = [];
  let totalCostUsd = 0;
  let totalPotentialProfitUsd = 0;
  let sentCount = 0;

  for (const ord of enabledOrders) {
    const ticker = String(ord.ticker ?? "").replace(/^KXNBAGAME-/, "KXNHLGAME-");
    const ledgerKey = `${date}:${ticker}`;
    if (st.ledger[ledgerKey]) {
      results.push({
        gameNo: ord.gameNo,
        ticker,
        winnerTeam: ord.winnerTeam,
        status: "ALREADY_EXECUTED",
        orderId: st.ledger[ledgerKey].orderId,
        contracts: st.ledger[ledgerKey].contracts,
        limitCents: st.ledger[ledgerKey].limitCents,
        estCostUsd: st.ledger[ledgerKey].estCostUsd,
        message: `قبلاً ثبت شده (Order ID: ${st.ledger[ledgerKey].orderId})`,
      });
      continue;
    }

    const mkt = liveMarkets[ticker];
    const liveAskCents = mkt && mkt.yesAskCents > 0 ? mkt.yesAskCents : ord.limitCents || 55;
    const limitCents = Math.min(99, Math.max(1, ord.limitCents > 0 ? ord.limitCents : liveAskCents));
    const stakeUsd = Math.max(1, Number(ord.stakeUsd || st.defaultStakeUsd || 3));
    const contracts = Math.max(1, Math.floor((stakeUsd * 100) / limitCents));
    const estCostUsd = Number(((contracts * limitCents) / 100).toFixed(2));
    const potentialProfitUsd = Number(((contracts * (100 - limitCents)) / 100).toFixed(2));

    if (mode === "dry_run") {
      totalCostUsd += estCostUsd;
      totalPotentialProfitUsd += potentialProfitUsd;
      results.push({
        gameNo: ord.gameNo,
        ticker,
        winnerTeam: ord.winnerTeam,
        marketFound: Boolean(mkt),
        status: mkt ? "DRY_RUN_READY" : "MARKET_NOT_OPEN_YET",
        contracts,
        limitCents,
        liveAskCents: mkt?.yesAskCents ?? null,
        liveBidCents: mkt?.yesBidCents ?? null,
        estCostUsd,
        potentialProfitUsd,
        message: mkt
          ? `آماده ارسال (DRY_RUN): خرید ${contracts} قرارداد YES @ ${limitCents}¢ در ${ticker} (هزینه: $${estCostUsd} • سود خالص برد: +$${potentialProfitUsd})`
          : `بازار ${ticker} هنوز در Kalshi باز نشده است (تخمین DRY_RUN @ ${limitCents}¢)`,
      });
      continue;
    }

    try {
      const ts = String(Date.now());
      const orderPath = "/trade-api/v2/portfolio/events/orders";
      const sig = signKalshiRequest(st.privateKeyPem, ts, "POST", orderPath);
      const clientOrderId = `nhl-${date.replace(/-/g, "")}-${ord.gameNo}-${Date.now()}`;
      const v2Payload = {
        ticker,
        side: "bid",
        count: `${contracts}.00`,
        price: (limitCents / 100).toFixed(4),
        time_in_force: "good_till_canceled",
        self_trade_prevention_type: "taker_at_cross",
        client_order_id: clientOrderId,
      };
      const resp = await fetch(`${getKalshiBaseUrl(st.env)}${orderPath}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "KALSHI-ACCESS-KEY": st.keyId,
          "KALSHI-ACCESS-TIMESTAMP": ts,
          "KALSHI-ACCESS-SIGNATURE": sig,
        },
        body: JSON.stringify(v2Payload),
      });
      const respText = await resp.text();
      let respJson: any = {};
      try { respJson = JSON.parse(respText); } catch {}

      const orderObj = respJson?.order ?? respJson;
      const orderId = orderObj?.order_id;

      if ((resp.status === 201 || resp.status === 200) && orderId) {
        sentCount++;
        totalCostUsd += estCostUsd;
        totalPotentialProfitUsd += potentialProfitUsd;
        st.ledger[ledgerKey] = {
          orderId: String(orderId),
          ticker,
          date,
          winnerTeam: ord.winnerTeam,
          contracts,
          limitCents,
          estCostUsd,
          status: String(orderObj?.status ?? "executed"),
          executedAt: new Date().toISOString(),
        };
        results.push({
          gameNo: ord.gameNo,
          ticker,
          winnerTeam: ord.winnerTeam,
          status: "EXECUTED",
          orderId,
          contracts,
          limitCents,
          estCostUsd,
          potentialProfitUsd,
          message: `ثبت موفق در Kalshi ✓ (Order ID: ${orderId})`,
        });
      } else {
        results.push({
          gameNo: ord.gameNo,
          ticker,
          winnerTeam: ord.winnerTeam,
          status: `ERROR_${resp.status}`,
          contracts,
          limitCents,
          estCostUsd,
          message: respJson?.error?.message ?? respJson?.message ?? respText.slice(0, 160),
        });
      }
    } catch (err) {
      results.push({
        gameNo: ord.gameNo,
        ticker,
        winnerTeam: ord.winnerTeam,
        status: "NETWORK_ERROR",
        message: (err as Error).message,
      });
    }
  }

  if (mode === "live" && sentCount > 0) {
    await writeKalshiState(st);
  }

  return {
    ok: true,
    mode,
    dryRun: mode === "dry_run",
    results,
    summary: {
      date,
      totalCards: enabledOrders.length,
      sentCount,
      totalCostUsd: Number(totalCostUsd.toFixed(2)),
      totalPotentialProfitUsd: Number(totalPotentialProfitUsd.toFixed(2)),
    },
  };
}

router.post("/kalshi/execute", async (req, res): Promise<void> => {
  const b = (req.body ?? {}) as { date?: string; orders?: KalshiCardOrderPlan[]; mode?: "dry_run" | "live" };
  const date = String(b.date ?? "").trim();
  const mode = b.mode === "live" ? "live" : "dry_run";
  let orders = Array.isArray(b.orders) ? b.orders : [];
  if (orders.length === 0 && date) {
    const st = await readKalshiState();
    orders = st.savedPlans[date]?.orders ?? [];
  }
  const out = await executeKalshiPlanOrders(date, orders, mode);
  res.status(out.ok ? 200 : 400).json(out);
});

setInterval(async () => {
  if (KALSHI_DRY_RUN_ONLY) return;
  try {
    const st = await readKalshiState();
    if (!st.autoScheduleEnabled || !st.keyId || !st.privateKeyPem) return;
    const nowEt = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
    const hh = String(nowEt.getHours()).padStart(2, "0");
    const mm = String(nowEt.getMinutes()).padStart(2, "0");
    const curHm = `${hh}:${mm}`;
    if (curHm === st.autoScheduleTimeEt) {
      for (const [planDate, planObj] of Object.entries(st.savedPlans)) {
        const unexec = (planObj.orders ?? []).filter((o) => o.enabled && !st.ledger[`${planDate}:${o.ticker}`]);
        if (unexec.length > 0) {
          await executeKalshiPlanOrders(planDate, unexec, "live");
        }
      }
    }
  } catch {
    // ignore background scheduler errors
  }
}, 30000);

// ============================================================================
// KALSHI NHL MULTIVARIATE COMBO (PARLAY 2-4 LEGS) ENDPOINT (KXNHLGAME)
// ============================================================================
export interface KalshiComboLegInput {
  gameNo: number;
  eventTicker: string;
  marketTicker: string;
  winnerTeam: string;
  yesAskCents: number;
  twinPct: number;
  agree: boolean;
}

router.post("/kalshi/combo", async (req, res): Promise<void> => {
  const b = (req.body ?? {}) as {
    date?: string;
    legs?: KalshiComboLegInput[];
    stakeUsd?: number;
    limitCents?: number;
    mode?: "dry_run" | "live";
  };
  const date = String(b.date ?? "").trim();
  const legs = Array.isArray(b.legs) ? b.legs : [];
  const mode = b.mode === "live" ? "live" : "dry_run";

  if (legs.length < 2 || legs.length > 4) {
    res.status(400).json({
      ok: false,
      error: "تعداد بازی‌های کمبو (Parlay) باید بین ۲ تا ۴ بازی باشد.",
    });
    return;
  }

  const probProduct = legs.reduce((acc, l) => {
    const p = Math.min(0.98, Math.max(0.02, (Number(l.yesAskCents) || 55) / 100));
    return acc * p;
  }, 1);
  const fairCents = Math.max(1, Math.min(95, Math.round(probProduct * 100)));
  const limitCents = Math.max(1, Math.min(98, Number(b.limitCents) > 0 ? Math.round(Number(b.limitCents)) : Math.min(95, fairCents + 1)));
  const stakeUsd = Math.max(1, Number(b.stakeUsd) || 4);
  const contracts = Math.max(1, Math.floor((stakeUsd * 100) / limitCents));
  const estCostUsd = Number(((contracts * limitCents) / 100).toFixed(2));
  const maxPayoutUsd = Number(contracts.toFixed(2));
  const potentialProfitUsd = Number((maxPayoutUsd - estCostUsd).toFixed(2));
  const multiplier = Number((100 / limitCents).toFixed(2));

  const st = await readKalshiState();
  const selectedMarkets = legs.map((l: any) => {
    const mTicker = String(l.marketTicker ?? l.ticker ?? "").trim().replace(/^KXNBAGAME-/, "KXNHLGAME-");
    const evTicker = String(l.eventTicker || mTicker.split("-").slice(0, 2).join("-")).trim().replace(/^KXNBAGAME-/, "KXNHLGAME-");
    return {
      event_ticker: evTicker,
      market_ticker: mTicker,
      side: "yes",
    };
  });

  const comboSportUpper = "NHL";
  let mveMarketTicker = `KXMVE-${comboSportUpper}-${date.replace(/-/g, "")}-${legs.map((l: any) => String(l.marketTicker ?? l.ticker ?? "").split("-").pop()).join("-")}`;
  let mveEventTicker = `KXMVE-${comboSportUpper}-${date.replace(/-/g, "")}`;
  let mveExchangeIndex = 1;
  let mveLiveAskCents: number | null = null;
  let mveLiveBidCents: number | null = null;
  let mveCreated = false;
  let mveLookupNote = "";

  if (!KALSHI_DRY_RUN_ONLY && st.keyId && st.privateKeyPem) {
    try {
      const colPath = "/trade-api/v2/multivariate_event_collections/KXMVESPORTSMULTIGAMEEXTENDED-R";
      const ts = String(Date.now());
      const sig = signKalshiRequest(st.privateKeyPem, ts, "POST", colPath);
      const colRes = await fetch(`${getKalshiBaseUrl(st.env)}${colPath}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "KALSHI-ACCESS-KEY": st.keyId,
          "KALSHI-ACCESS-TIMESTAMP": ts,
          "KALSHI-ACCESS-SIGNATURE": sig,
        },
        body: JSON.stringify({
          selected_markets: selectedMarkets,
          with_market_payload: true,
        }),
      });
      const colTxt = await colRes.text();
      let colJson: any = {};
      try { colJson = JSON.parse(colTxt); } catch {}
      if (colRes.ok && colJson?.market_ticker) {
        mveMarketTicker = String(colJson.market_ticker);
        mveEventTicker = String(colJson.event_ticker ?? mveEventTicker);
        mveCreated = true;
        if (colJson?.market) {
          if (typeof colJson.market.exchange_index === "number") {
            mveExchangeIndex = colJson.market.exchange_index;
          }
          if (colJson.market.yes_ask_dollars) {
            mveLiveAskCents = Math.round(Number(colJson.market.yes_ask_dollars) * 100);
          }
          if (colJson.market.yes_bid_dollars) {
            mveLiveBidCents = Math.round(Number(colJson.market.yes_bid_dollars) * 100);
          }
        }
      } else {
        mveLookupNote = colJson?.error?.message ?? colJson?.message ?? colTxt.slice(0, 140);
      }
    } catch (e) {
      mveLookupNote = (e as Error).message;
    }
  }

  if (KALSHI_DRY_RUN_ONLY || mode === "dry_run" || !st.keyId || !st.privateKeyPem) {
    res.json({
      ok: true,
      mock: KALSHI_DRY_RUN_ONLY || !Boolean(st.keyId && st.privateKeyPem),
      dryRun: true,
      mode: "dry_run",
      date,
      comboTicker: mveMarketTicker,
      comboEventTicker: mveEventTicker,
      mveCreated,
      mveLookupNote,
      legs,
      fairCents,
      limitCents,
      mveLiveAskCents,
      mveLiveBidCents,
      stakeUsd,
      contracts,
      estCostUsd,
      maxPayoutUsd,
      potentialProfitUsd,
      multiplier,
      message: mveCreated
        ? `تیکر رسمی کمبوی NHL (${legs.length} بازی) در Kalshi استعلام شد: ${mveMarketTicker} • خرید ${contracts} قرارداد @ ${limitCents}¢ (ضریب ${multiplier}x • هزینه $${estCostUsd} • سود خالص برد: +$${potentialProfitUsd})`
        : `پیش‌نمایش ایمن کمبوی NHL (${legs.length} بازی • DRY_RUN) آماده است • خرید ${contracts} قرارداد @ ${limitCents}¢ (ضریب ${multiplier}x • هزینه $${estCostUsd} • سود خالص برد: +$${potentialProfitUsd})`,
    });
    return;
  }

  try {
    const bPath = "/trade-api/v2/portfolio/balance";
    const bTs = String(Date.now());
    const bSig = signKalshiRequest(st.privateKeyPem, bTs, "GET", bPath);
    const bRes = await fetch(`${getKalshiBaseUrl(st.env)}${bPath}`, {
      headers: {
        "KALSHI-ACCESS-KEY": st.keyId,
        "KALSHI-ACCESS-TIMESTAMP": bTs,
        "KALSHI-ACCESS-SIGNATURE": bSig,
      },
    });
    if (bRes.ok) {
      const bData: any = await bRes.json();
      const bd: any[] = Array.isArray(bData?.balance_breakdown) ? bData.balance_breakdown : [];
      const curShardBal = Number(bd.find((x) => x.exchange_index === mveExchangeIndex)?.balance ?? 0);
      if (curShardBal < estCostUsd * 1.20 + 0.5) {
        const donor = [...bd]
          .filter((x) => x.exchange_index !== mveExchangeIndex && Number(x.balance) >= 1)
          .sort((a, b) => Number(b.balance) - Number(a.balance))[0];
        if (donor) {
          const transferUsd = Math.min(Number(donor.balance), Math.max(estCostUsd * 1.25 - curShardBal + 1.5, 5));
          const amountCenticents = Math.floor(transferUsd * 10000);
          if (amountCenticents > 0) {
            const tPath = "/trade-api/v2/portfolio/intra_exchange_instance_transfer";
            const tTs = String(Date.now());
            const tSig = signKalshiRequest(st.privateKeyPem, tTs, "POST", tPath);
            await fetch(`${getKalshiBaseUrl(st.env)}${tPath}`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "KALSHI-ACCESS-KEY": st.keyId,
                "KALSHI-ACCESS-TIMESTAMP": tTs,
                "KALSHI-ACCESS-SIGNATURE": tSig,
              },
              body: JSON.stringify({
                source: "event_contract",
                destination: "event_contract",
                source_exchange_shard: donor.exchange_index,
                destination_exchange_shard: mveExchangeIndex,
                amount: amountCenticents,
              }),
            });
            await new Promise((r) => setTimeout(r, 2000));
          }
        }
      }
    }
  } catch {}

  let rfqId: string | null = null;
  try {
    const rfqPath = "/trade-api/v2/communications/rfqs";
    const rfqTs = String(Date.now());
    const rfqSig = signKalshiRequest(st.privateKeyPem, rfqTs, "POST", rfqPath);
    const rfqRes = await fetch(`${getKalshiBaseUrl(st.env)}${rfqPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": st.keyId,
        "KALSHI-ACCESS-TIMESTAMP": rfqTs,
        "KALSHI-ACCESS-SIGNATURE": rfqSig,
      },
      body: JSON.stringify({
        market_ticker: mveMarketTicker,
        target_cost_dollars: estCostUsd.toFixed(2),
        rest_remainder: true,
        replace_existing: false,
      }),
    });
    if (rfqRes.ok) {
      const rfqJson: any = await rfqRes.json();
      rfqId = rfqJson?.id ? String(rfqJson.id) : null;
    }
  } catch {}

  try {
    const orderPath = "/trade-api/v2/portfolio/events/orders";
    const oTs = String(Date.now());
    const oSig = signKalshiRequest(st.privateKeyPem, oTs, "POST", orderPath);
    const clientOrderId = `nhl-combo-${date.replace(/-/g, "")}-${Date.now()}`;
    const v2Payload = {
      ticker: mveMarketTicker,
      side: "bid",
      count: `${contracts}.00`,
      price: (limitCents / 100).toFixed(4),
      time_in_force: "good_till_canceled",
      self_trade_prevention_type: "taker_at_cross",
      client_order_id: clientOrderId,
    };
    const oRes = await fetch(`${getKalshiBaseUrl(st.env)}${orderPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": st.keyId,
        "KALSHI-ACCESS-TIMESTAMP": oTs,
        "KALSHI-ACCESS-SIGNATURE": oSig,
      },
      body: JSON.stringify(v2Payload),
    });
    const oTxt = await oRes.text();
    let oJson: any = {};
    try { oJson = JSON.parse(oTxt); } catch {}
    const orderObj = oJson?.order ?? oJson;
    const orderId = orderObj?.order_id;

    if ((oRes.status === 201 || oRes.status === 200) && orderId) {
      st.ledger[`${date}:COMBO:${mveMarketTicker}`] = {
        orderId: String(orderId),
        ticker: mveMarketTicker,
        date,
        winnerTeam: legs.map((l) => l.winnerTeam).join(" + "),
        contracts,
        limitCents,
        estCostUsd,
        status: "executed",
        executedAt: new Date().toISOString(),
      };
      await writeKalshiState(st);
      res.json({
        ok: true,
        mode: "live",
        status: "EXECUTED",
        orderId,
        rfqId,
        comboTicker: mveMarketTicker,
        legs,
        contracts,
        limitCents,
        estCostUsd,
        maxPayoutUsd,
        potentialProfitUsd,
        multiplier,
        message: `سفارش کمبوی NHL (${legs.length} بازی) با موفقیت در Kalshi ثبت شد ✓ (Order ID: ${orderId}${rfqId ? ` • RFQ: ${rfqId}` : ""})`,
      });
      return;
    }

    res.json({
      ok: false,
      mode: "live",
      status: `ERROR_${oRes.status}`,
      rfqId,
      comboTicker: mveMarketTicker,
      legs,
      contracts,
      limitCents,
      estCostUsd,
      maxPayoutUsd,
      potentialProfitUsd,
      multiplier,
      message: oJson?.error?.message ?? oJson?.message ?? oTxt.slice(0, 180),
    });
  } catch (err) {
    res.status(500).json({
      ok: false,
      error: (err as Error).message,
    });
  }
});

router.get("/kalshi/audit", async (_req, res): Promise<void> => {
  try {
    const st = await readKalshiState();
    if (KALSHI_DRY_RUN_ONLY || !st.keyId || !st.privateKeyPem) {
      res.json({
        ok: true,
        mock: true,
        dryRun: true,
        balance: { balance: 0, portfolio_value: 0 },
        settlements: { settlements: [] },
        fills: { fills: [] },
        orders: { orders: [] },
      });
      return;
    }
    const fetchKalshi = async (p: string) => {
      const ts = String(Date.now());
      const sig = signKalshiRequest(st.privateKeyPem, ts, "GET", p.split("?")[0]);
      const r = await fetch(`${getKalshiBaseUrl(st.env)}${p}`, {
        headers: {
          "KALSHI-ACCESS-KEY": st.keyId,
          "KALSHI-ACCESS-TIMESTAMP": ts,
          "KALSHI-ACCESS-SIGNATURE": sig,
        },
      });
      return await r.json();
    };
    const [settlements, fills, orders, balance] = await Promise.all([
      fetchKalshi("/trade-api/v2/portfolio/settlements?limit=50"),
      fetchKalshi("/trade-api/v2/portfolio/fills?limit=50"),
      fetchKalshi("/trade-api/v2/portfolio/orders?limit=50"),
      fetchKalshi("/trade-api/v2/portfolio/balance"),
    ]);
    res.json({ ok: true, balance, settlements, fills, orders });
  } catch (err) {
    res.status(500).json({ ok: false, error: (err as Error).message });
  }
});

// ---------------------------------------------------------------------------
// NHL PURE DEG1 = 88 SIGNAL, LIVE ESPN SYNC & ACTIVE ROSTER/TOI SYNC ENDPOINTS
// ---------------------------------------------------------------------------

router.get("/nhl/predictions", async (_req, res): Promise<void> => {
  try {
    const file = await resolveNhlPublicFile("nhl_predictions_2024_2027.json");
    const raw = await fs.readFile(file, "utf-8");
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.send(raw);
  } catch (e) {
    res.status(500).json({ ok: false, error: (e as Error).message, games: [] });
  }
});

router.get("/nhl/history-pack", async (_req, res): Promise<void> => {
  try {
    const file = await resolveNhlPublicFile("nhl_history_pack_2010_2026.json");
    const raw = await fs.readFile(file, "utf-8");
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.send(raw);
  } catch (e) {
    res.status(500).json({ ok: false, error: (e as Error).message });
  }
});

let nhlSyncing = false;

async function handleNhlLiveScoreSync(req: any, res: any): Promise<void> {
  if (nhlSyncing) {
    res.status(409).json({ ok: false, error: "بروزرسانی نتایج واقعی NHL در حال انجام است." });
    return;
  }
  const b = (req.body ?? {}) as Record<string, unknown>;
  const startDate = typeof b.startDate === "string" ? b.startDate.trim() : "";
  const endDate = typeof b.endDate === "string" ? b.endDate.trim() : "";
  const targetDate = typeof b.targetDate === "string" ? b.targetDate.trim() : "";

  nhlSyncing = true;
  try {
    const scriptCandidates = [
      path.resolve(__dirname, "../../python/nhl_live_sync.py"),
      path.resolve(__dirname, "../python/nhl_live_sync.py"),
    ];
    let scriptPath = scriptCandidates[0];
    for (const sc of scriptCandidates) {
      try {
        await fs.access(sc);
        scriptPath = sc;
        break;
      } catch {}
    }
    const args = [scriptPath];
    if (/^\d{4}-\d{2}-\d{2}$/.test(startDate)) args.push("--start-date", startDate);
    if (/^\d{4}-\d{2}-\d{2}$/.test(endDate)) args.push("--end-date", endDate);
    if (/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) args.push("--target-date", targetDate);

    const out = await new Promise<{ code: number; stdout: string }>((resolve) => {
      const child = spawn("python3", args, { env: process.env, cwd: path.dirname(scriptPath) });
      let buf = "";
      child.stdout.on("data", (d: Buffer) => (buf += d.toString()));
      child.stderr.on("data", (d: Buffer) => (buf += d.toString()));
      child.on("error", (err) => resolve({ code: -1, stdout: err.message }));
      child.on("close", (c) => resolve({ code: c ?? -1, stdout: buf }));
    });

    let parsed: any = null;
    for (const line of out.stdout.split(/\r?\n/).reverse()) {
      if (line.startsWith("__NHL_SYNC__ ") || line.startsWith("__NBA_SYNC__ ")) {
        const pfx = line.startsWith("__NHL_SYNC__ ") ? "__NHL_SYNC__ " : "__NBA_SYNC__ ";
        try {
          parsed = JSON.parse(line.slice(pfx.length));
        } catch {}
        break;
      }
    }
    if (out.code === 0 && parsed?.ok) {
      res.json(parsed);
    } else {
      res.status(500).json({ ok: false, error: out.stdout.slice(-600) || `Exited ${out.code}` });
    }
  } finally {
    nhlSyncing = false;
  }
}

router.post("/nhl/sync", handleNhlLiveScoreSync);
router.post("/nba/sync", handleNhlLiveScoreSync);

let nhlRosterSyncing = false;

async function handleNhlRosterSync(req: any, res: any): Promise<void> {
  if (nhlRosterSyncing) {
    res.status(409).json({ ok: false, error: "بروزرسانی زنده مصدومان (OUT/IR) و لیست بازیکنان NHL در حال انجام است." });
    return;
  }
  const b = (req.body ?? {}) as Record<string, unknown>;
  const targetDate = typeof b.targetDate === "string" ? b.targetDate.trim() : "";

  nhlRosterSyncing = true;
  try {
    const scriptCandidates = [
      path.resolve(__dirname, "../../python/fusion_roster_sync.py"),
      path.resolve(__dirname, "../python/fusion_roster_sync.py"),
    ];
    let scriptPath = scriptCandidates[0];
    for (const sc of scriptCandidates) {
      try {
        await fs.access(sc);
        scriptPath = sc;
        break;
      } catch {}
    }
    const args = [scriptPath];
    if (/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      args.push("--target-date", targetDate);
    }

    const out = await new Promise<{ code: number; stdout: string }>((resolve) => {
      const child = spawn("python3", args, { env: process.env, cwd: path.dirname(scriptPath) });
      let buf = "";
      child.stdout.on("data", (d: Buffer) => (buf += d.toString()));
      child.stderr.on("data", (d: Buffer) => (buf += d.toString()));
      child.on("error", (err) => resolve({ code: -1, stdout: err.message }));
      child.on("close", (c) => resolve({ code: c ?? -1, stdout: buf }));
    });

    let parsed: any = null;
    for (const line of out.stdout.split(/\r?\n/).reverse()) {
      if (line.startsWith("__NHL_ROSTER_SYNC__ ") || line.startsWith("__NBA_ROSTER_SYNC__ ")) {
        const pfx = line.startsWith("__NHL_ROSTER_SYNC__ ") ? "__NHL_ROSTER_SYNC__ " : "__NBA_ROSTER_SYNC__ ";
        try {
          parsed = JSON.parse(line.slice(pfx.length));
        } catch {}
        break;
      }
    }
    if (out.code === 0 && parsed?.ok) {
      res.json(parsed);
    } else {
      res.status(500).json({ ok: false, error: out.stdout.slice(-600) || `Exited ${out.code}` });
    }
  } finally {
    nhlRosterSyncing = false;
  }
}

router.post("/nhl/sync-rosters", handleNhlRosterSync);
router.post("/nba/sync-rosters", handleNhlRosterSync);

export default router;
