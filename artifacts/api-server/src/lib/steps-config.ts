import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PYTHON_DIR = path.resolve(__dirname, "..", "python");

export type SheetLink = {
  label: string;
  spreadsheetId: string;
  tab?: string;
  url: string;
  market?: string;
};

export type StepDef = {
  id: number;
  name: string;
  description: string;
  runtime: "python" | "node";
  implemented: boolean;
  command: string;
  args: string[];
  inputs: SheetLink[];
  outputs: SheetLink[];
};

const INPUT_SHEET_ID = (process.env.NHL_FUSION_INPUT_SHEET_ID ?? "").trim();
const CALC_SHEET_ID = (process.env.NHL_FUSION_CALC_SHEET_ID ?? "").trim();

const sheetUrl = (id: string, tab?: string): string => {
  if (!id) return "";
  return tab
    ? `https://docs.google.com/spreadsheets/d/${id}/edit#gid=0&fvid=${encodeURIComponent(tab)}`
    : `https://docs.google.com/spreadsheets/d/${id}/edit`;
};

export const STEPS: StepDef[] = [
  {
    id: 1,
    name: "NHL Orthogonal Dual-Engine Fusion v82 (Team+Arena × Active-8/12 TOI Players • DEG1=88)",
    description:
      "Combines NHL Team+Arena (DEG1=88) and NHL Player Signal Mode C (Active-8 & Active-12 TOI-weighted Players + Jersey Number • DEG1=88) across all 14 Fusion Modes with Ranked Weighted 6-Box Referee v82.",
    runtime: "python",
    implemented: true,
    command: "python3",
    args: [path.join(PYTHON_DIR, "nhl_live_sync.py")],
    inputs: INPUT_SHEET_ID
      ? [
          {
            label: "NHL-FUSION-INPUT (Sheet1, NHL-TEAM-GEM, NHL-PLAYERS-GEM, NHL_SCHEDULE_2025_2027)",
            spreadsheetId: INPUT_SHEET_ID,
            tab: "Sheet1",
            url: sheetUrl(INPUT_SHEET_ID),
          },
        ]
      : [],
    outputs: CALC_SHEET_ID
      ? [
          {
            label: "NHL-FUSION-CALCULATION (Fusion_Benchmark_Summary, Fusion_Predictions_Master)",
            spreadsheetId: CALC_SHEET_ID,
            tab: "Fusion_Benchmark_Summary",
            url: sheetUrl(CALC_SHEET_ID),
          },
        ]
      : [],
  },
];

export function getStep(id: number): StepDef | undefined {
  return STEPS.find((s) => s.id === id);
}
