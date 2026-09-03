/**
 * Der Zugang zur API.
 *
 * Alle Zahlen kommen als Rohwerte oder als `null`. `null` heißt "nicht
 * messbar" und wird in der Oberfläche zum Strich — es wird nirgends in
 * eine 0 umgedeutet.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

export interface SyncState {
  state: 'gesund' | 'verzoegert' | 'still' | 'fehler' | 'nie';
  minutes_ago: number | null;
  last_success: string | null;
  last_error: string | null;
  source: string | null;
  deals_imported?: number;
}

export interface Account {
  id: number;
  label: string;
  broker: string | null;
  currency: string;
  phase: string;
  status: string;
  starting_balance: number | null;
  limits: {
    daily_loss: number | null;
    max_loss: number | null;
    consistency: number | null;
    warn_threshold: number | null;
    profit_target: number | null;
  };
  sync: SyncState;
}

export interface Metrics {
  trade_count: number;
  wins: number;
  losses: number;
  scratches: number;
  net_pnl: number;
  gross_profit: number;
  gross_loss: number;
  total_costs: number;
  win_rate: number | null;
  profit_factor: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  win_loss_ratio: number | null;
  expectancy: number | null;
  expectancy_r: number | null;
  max_drawdown: number;
  recovery_factor: number | null;
  consistency: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  trading_days: number;
  trades_without_stop: number;
}

export interface Buffer {
  label: string;
  used: number | null;
  limit: number | null;
  remaining: number | null;
  ratio: number | null;
  warn_at: number | null;
  state: 'ok' | 'warnung' | 'gerissen';
  measurable: boolean;
  reason: string | null;
}

export interface Overview {
  metrics: Metrics;
  score: {
    total: number | null;
    parts: Record<string, number | null>;
    missing: string[];
  };
  rules: {
    daily_loss: Buffer;
    max_loss: Buffer;
    consistency: Buffer;
    account_lost: boolean;
    most_urgent: string;
  };
  equity_curve: { t: string; equity: number; drawdown: number }[];
  sync: SyncState;
}

export interface Tag {
  id: number;
  label: string;
  kind: 'setup' | 'fehler' | 'emotion';
}

export interface Trade {
  id: number;
  position_id: number;
  symbol: string;
  /** Nachkommastellen des Instruments — die Preise werden damit gesetzt. */
  digits: number;
  direction: 'long' | 'short';
  opened_at: string | null;
  closed_at: string | null;
  duration_seconds: number | null;
  volume: number;
  exit_volume: number;
  avg_entry: number | null;
  avg_exit: number | null;
  gross_pnl: number;
  costs: number;
  net_pnl: number;
  initial_sl: number | null;
  risk_amount: number | null;
  r_multiple: number | null;
  outcome: 'win' | 'loss' | 'scratch';
  is_open: boolean;
  partial: boolean;
  note: string | null;
  tags: Tag[];
}

export interface Execution {
  ticket: number;
  time: string;
  type: string;
  entry: string;
  volume: number;
  price: number;
  profit: number;
  commission: number;
  swap: number;
  fee: number;
}

export interface TradeDetail extends Trade {
  executions: Execution[];
}

export interface CalendarDay {
  date: string;
  weekday: number;
  iso_week: number;
  pnl: number | null;
  trades: number;
  wins: number;
  win_rate: number | null;
  weekend: boolean;
}

export interface CalendarMonth {
  year: number;
  month: number;
  days: CalendarDay[];
  weeks: { iso_week: number; pnl: number; trades: number; days: number }[];
  month_pnl: number;
  trading_days: number;
  best_day: CalendarDay | null;
  worst_day: CalendarDay | null;
}

export interface ReportGroup {
  key: string;
  trades: number;
  below_min_sample: boolean;
  net_pnl: number;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  expectancy_r: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  wins: number;
  losses: number;
}

export interface Report {
  dimension: string;
  min_sample: number;
  groups: ReportGroup[];
  total_trades: number;
}

export interface Filters {
  account_id?: number | null;
  von?: string | null;
  bis?: string | null;
  symbol?: string | null;
  direction?: string | null;
}

function query(params: Record<string, unknown>): string {
  const suchen = new URLSearchParams();
  for (const [schluessel, wert] of Object.entries(params)) {
    if (wert !== null && wert !== undefined && wert !== '') {
      suchen.set(schluessel, String(wert));
    }
  }
  const text = suchen.toString();
  return text ? `?${text}` : '';
}

async function hole<T>(pfad: string, init?: RequestInit): Promise<T> {
  const antwort = await fetch(`${API_BASE}${pfad}`, {
    cache: 'no-store',
    ...init,
  });
  if (!antwort.ok) {
    let text = `${antwort.status} ${antwort.statusText}`;
    try {
      const koerper = await antwort.json();
      if (koerper?.detail) text = String(koerper.detail);
    } catch {
      /* Antwort war kein JSON — die Statuszeile muss reichen. */
    }
    throw new Error(text);
  }
  return antwort.json() as Promise<T>;
}

export const api = {
  accounts: () => hole<Account[]>('/api/accounts'),

  overview: (f: Filters) => hole<Overview>(`/api/overview${query({ ...f })}`),

  trades: (f: Filters & { limit?: number; offset?: number; outcome?: string }) =>
    hole<{ total: number; limit: number; offset: number; trades: Trade[] }>(
      `/api/trades${query({ ...f })}`,
    ),

  trade: (id: number) => hole<TradeDetail>(`/api/trades/${id}`),

  calendar: (year: number, month: number, account_id?: number | null) =>
    hole<CalendarMonth>(`/api/calendar${query({ year, month, account_id })}`),

  report: (dimension: string, f: Filters & { min_sample?: number }) =>
    hole<Report>(`/api/reports/${dimension}${query({ ...f })}`),

  symbols: (account_id?: number | null) =>
    hole<string[]>(`/api/symbols${query({ account_id })}`),
};
