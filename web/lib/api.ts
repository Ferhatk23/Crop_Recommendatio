/**
 * Der Zugang zur API.
 *
 * Alle Zahlen kommen als Rohwerte oder als `null`. `null` heißt "nicht
 * messbar" und wird in der Oberfläche zum Strich — es wird nirgends in
 * eine 0 umgedeutet.
 */

/**
 * Wohin die Anfragen gehen.
 *
 * Im Betrieb steht hier eine **leere Zeichenkette**, und das ist der
 * ganze Trick: Dann sind die Pfade relativ (`/api/trades`), und der
 * Reverse Proxy reicht sie an die API weiter. Oberfläche und API liegen
 * damit auf demselben Ursprung -- und drei Fehlerquellen fallen auf
 * einmal weg:
 *
 * * **Kein CORS.** Keine Freigabeliste, die man beim Umzug auf eine neue
 *   Domain nachziehen muss und deren Vergessen sich als "Failed to
 *   fetch" zeigt.
 * * **Kein Cookie-Ärger.** Das Sitzungs-Cookie ist same-site, also
 *   unabhängig davon, wie streng der Browser mit fremden Ursprüngen
 *   umgeht.
 * * **Kein zweiter Port nach draußen.** Nur der Proxy hört auf 443; API
 *   und Oberfläche bleiben auf 127.0.0.1.
 *
 * `??` und nicht `||`: Eine leere Zeichenkette ist ein *gültiger* Wert
 * und darf nicht auf den Entwicklungs-Standard zurückfallen. Mit `||`
 * würde der Betrieb still auf `127.0.0.1:8000` zeigen -- und das wäre
 * aus dem Browser des iPhones der Rechner des Nutzers selbst.
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

export type KontoPhase = 'challenge' | 'verifikation' | 'funded' | 'live';
export type KontoStatus = 'aktiv' | 'bestanden' | 'verloren' | 'archiviert';

export const PHASEN: { id: KontoPhase; label: string }[] = [
  { id: 'challenge', label: 'Challenge' },
  { id: 'verifikation', label: 'Verifikation' },
  { id: 'funded', label: 'Funded' },
  { id: 'live', label: 'Eigenes Konto' },
];

export const STATUS: { id: KontoStatus; label: string }[] = [
  { id: 'aktiv', label: 'aktiv' },
  { id: 'bestanden', label: 'bestanden' },
  { id: 'verloren', label: 'verloren' },
  { id: 'archiviert', label: 'archiviert' },
];

export interface Limits {
  daily_loss: number | null;
  max_loss: number | null;
  consistency: number | null;
  warn_threshold: number | null;
  profit_target: number | null;
}

export interface Account {
  id: number;
  label: string;
  login: string | null;
  broker: string | null;
  server: string | null;
  currency: string;
  phase: string;
  status: string;
  starting_balance: number | null;
  limits: Limits;
  /** Zahl der Ausfuehrungen - ab eins ist das Konto nicht mehr loeschbar. */
  deal_count: number;
  sync: SyncState;
}

/** Was sich an einem Konto eintragen laesst. */
export interface KontoFelder {
  label: string;
  login?: string | null;
  broker?: string | null;
  server?: string | null;
  currency?: string;
  phase?: string;
  status?: string;
  starting_balance?: number;
  daily_loss_limit?: number | null;
  max_loss_limit?: number | null;
  consistency_limit?: number | null;
  warn_threshold?: number | null;
  profit_target?: number | null;
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

export type TagKind = 'setup' | 'fehler' | 'emotion';

/** Die drei Arten, an der Form unterscheidbar — nicht nur an der Farbe. */
export const TAG_ARTEN: { id: TagKind; label: string }[] = [
  { id: 'setup', label: 'Setup' },
  { id: 'fehler', label: 'Fehler' },
  { id: 'emotion', label: 'Emotion' },
];

export interface Tag {
  id: number;
  label: string;
  kind: TagKind;
}

/** Ein bereits vergebener Tag, mit Häufigkeit — für die Vorschläge. */
export interface TagVorschlag extends Tag {
  count: number;
}

export interface JournalEintrag {
  date: string;
  body: string;
  mood: number | null;
  updated_at: string | null;
}

export interface PlaybookRegel {
  id: number;
  group: string;
  text: string;
  /** Abhakbar, also eine echte Vorbedingung — nicht bloß ein Merksatz. */
  checkable: boolean;
}

/**
 * Eine Regel auf dem Weg zum Server.
 *
 * `id` fehlt, solange sie neu ist. Vorhandene behalten ihre — daran
 * hängen sämtliche Antworten, die je an ihr gesetzt wurden.
 */
export interface RegelEingabe {
  id?: number;
  group: string;
  text: string;
  checkable: boolean;
}

export interface Playbook {
  id: number;
  name: string;
  description: string | null;
  rules: PlaybookRegel[];
  /** Wie viele Trades daran hängen — entscheidet über das Löschen. */
  trade_count: number;
}

/**
 * Die Antwort auf eine Regel bei einem Trade.
 *
 * Der dritte Zustand steht nicht hier drin, sondern in der Abwesenheit:
 * Eine Regel ohne Eintrag ist **unbeantwortet**, nicht gebrochen.
 */
export interface RegelAntwort {
  rule_id: number;
  checked: boolean;
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
  playbook_id: number | null;
  tags: Tag[];
  /** Nur die Antworten zum *zugeordneten* Playbook. */
  rule_checks: RegelAntwort[];
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
  /**
   * Wahr bei Tag-Rubriken: Ein Trade kann in mehreren Gruppen zählen,
   * die Gruppen sind also keine Aufteilung. Die Oberfläche muss das
   * sagen, sonst addiert der Leser sie zu einer falschen Summe.
   */
  overlapping: boolean;
}

/** Eine Regel in der Regeltreue-Auswertung. */
export interface RegelBilanz {
  rule_id: number;
  playbook_id: number;
  playbook: string;
  group: string;
  text: string;
  answered: number;
  kept: number;
  broken: number;
  /** `null`, solange keine Antwort da ist — 0 hieße „nie eingehalten". */
  rate: number | null;
  below_min_sample: boolean;
  pnl_kept: number;
  pnl_broken: number;
}

export interface Regeltreue {
  min_sample: number;
  /** Genau zwei: `eingehalten` und `gebrochen`. */
  groups: ReportGroup[];
  /**
   * Trades, die noch nicht vollständig durchgegangen sind. Sie stehen
   * bewusst außerhalb des Vergleichs: Wer sie zu den gebrochenen zählte,
   * bestrafte den, der noch nicht dazugekommen ist.
   */
  unanswered: number;
  total_trades: number;
  rules: RegelBilanz[];
  overlapping: boolean;
  /** Immer wahr: Kein Häkchen kommt aus MT5, jedes aus dem Kopf. */
  self_reported: boolean;
}

/**
 * Was an einem Trade noch aussteht.
 *
 * Jeder Wert sagt genau eine nachprüfbare Sache. Es gibt bewusst kein
 * zusammengesetztes „erledigt": Wann ein Trade durchgearbeitet ist, weiß
 * nur der Händler — eine erfundene Definition stünde am Ende als
 * Fortschrittsbalken da, der etwas anderes misst, als er behauptet.
 */
export type Nacharbeit =
  | 'unberuehrt'
  | 'regeln_offen'
  | 'ohne_notiz'
  | 'ohne_tag'
  | 'ohne_playbook';

export const NACHARBEIT: { id: Nacharbeit | ''; label: string }[] = [
  { id: '', label: 'Alle Trades' },
  { id: 'unberuehrt', label: 'noch nicht angesehen' },
  { id: 'regeln_offen', label: 'Regeln offen' },
  { id: 'ohne_notiz', label: 'ohne Notiz' },
  { id: 'ohne_tag', label: 'ohne Tag' },
  { id: 'ohne_playbook', label: 'ohne Playbook' },
];

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

/**
 * Wird geworfen, wenn die Anmeldung fehlt oder abgelaufen ist.
 *
 * Eine eigene Klasse, keine Zeichenkette: Der Aufrufer muss diesen Fall
 * von einem echten Fehler unterscheiden können. „Nicht angemeldet" ist
 * kein Defekt, sondern ein Zustand — und gehört auf die Anmeldeseite,
 * nicht in eine rote Fehlermeldung.
 */
export class NichtAngemeldet extends Error {
  constructor(nachricht = 'Nicht angemeldet') {
    super(nachricht);
    this.name = 'NichtAngemeldet';
  }
}

async function hole<T>(pfad: string, init?: RequestInit): Promise<T> {
  const antwort = await fetch(`${API_BASE}${pfad}`, {
    cache: 'no-store',
    // Ohne das schickt der Browser das Sitzungs-Cookie bei einer
    // Anfrage an einen anderen Ursprung nicht mit — und die App wäre
    // dauerhaft abgemeldet, obwohl die Anmeldung geklappt hat.
    credentials: 'include',
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
    if (antwort.status === 401) throw new NichtAngemeldet(text);
    throw new Error(text);
  }
  return antwort.json() as Promise<T>;
}

export interface Nutzer {
  id: number;
  email: string;
}

export interface Sitzung {
  id: number;
  device: string | null;
  created_at: string | null;
  last_seen: string | null;
  expires_at: string | null;
}

export const api = {
  /* --- Anmeldung ------------------------------------------------------ */

  anmelden: (email: string, password: string) =>
    hole<Nutzer>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }),

  abmelden: () => hole<{ status: string }>('/api/auth/logout', { method: 'POST' }),

  ich: () => hole<Nutzer>('/api/auth/me'),

  sitzungen: () => hole<Sitzung[]>('/api/auth/sessions'),

  sitzung_beenden: (id: number) =>
    hole<{ status: string }>(`/api/auth/sessions/${id}`, { method: 'DELETE' }),

  /* --- Daten ---------------------------------------------------------- */

  accounts: () => hole<Account[]>('/api/accounts'),

  konto_anlegen: (felder: KontoFelder) =>
    hole<Account>('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(felder),
    }),

  /** Aendert nur die mitgegebenen Felder - wie bei den Trades. */
  konto_aendern: (id: number, felder: Partial<KontoFelder>) =>
    hole<Account>(`/api/accounts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(felder),
    }),

  konto_loeschen: (id: number) =>
    hole<{ status: string }>(`/api/accounts/${id}`, { method: 'DELETE' }),

  overview: (f: Filters) => hole<Overview>(`/api/overview${query({ ...f })}`),

  trades: (
    f: Filters & {
      limit?: number;
      offset?: number;
      outcome?: string;
      nachbearbeitung?: Nacharbeit | '';
    },
  ) =>
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

  /* --- Schreiben ------------------------------------------------------ */

  /**
   * Ändert nur die mitgegebenen Felder.
   *
   * Deshalb `Partial`: Ein weggelassenes Feld bleibt auf dem Server, wie
   * es war. Wer hier `{ note }` schickt, fasst die Playbook-Zuordnung
   * nicht an — und umgekehrt.
   */
  trade_aendern: (
    id: number,
    aenderung: { note?: string | null; playbook_id?: number | null },
  ) =>
    // Antwort ist der Trade *ohne* Ausführungen: Die ändern sich beim
    // Schreiben nicht, und sie nachzuliefern wäre eine Abfrage für
    // Daten, die der Aufrufer schon hat.
    hole<Trade>(`/api/trades/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(aenderung),
    }),

  /**
   * Setzt die Tags auf genau diese Liste.
   *
   * Die vollständige Liste statt einzelner Zugriffe: Zweimal geschickt
   * ergibt zweimal dasselbe. Ein doppelter Klick kann so nichts anrichten.
   */
  tags_setzen: (id: number, tags: { label: string; kind: TagKind }[]) =>
    hole<Trade>(`/api/trades/${id}/tags`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags }),
    }),

  tags: (account_id?: number | null) =>
    hole<TagVorschlag[]>(`/api/tags${query({ account_id })}`),

  journal: (tag: string, account_id: number) =>
    hole<JournalEintrag>(`/api/journal/${tag}${query({ account_id })}`),

  journal_schreiben: (
    tag: string,
    account_id: number,
    eintrag: { body: string; mood?: number | null },
  ) =>
    hole<JournalEintrag>(`/api/journal/${tag}${query({ account_id })}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(eintrag),
    }),

  playbooks: (account_id?: number | null) =>
    hole<Playbook[]>(`/api/playbooks${query({ account_id })}`),

  playbook_anlegen: (eingabe: {
    name: string;
    description?: string | null;
    rules?: RegelEingabe[];
  }) =>
    hole<Playbook>('/api/playbooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(eingabe),
    }),

  playbook_aendern: (
    id: number,
    aenderung: { name?: string; description?: string | null },
  ) =>
    hole<Playbook>(`/api/playbooks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(aenderung),
    }),

  /**
   * Setzt die Regelliste auf genau diese Reihenfolge.
   *
   * Regeln mit `id` werden fortgeführt — ohne das verlöre jede Regel bei
   * jeder Tippfehlerkorrektur ihre Antworten.
   *
   * Streicht der Aufruf eine Regel, an der Antworten hängen, kommt ein
   * 409 zurück. Das ist kein Fehler, sondern die Rückfrage: erst mit
   * `antworten_verwerfen` geht es durch.
   */
  playbook_regeln_setzen: (
    id: number,
    regeln: RegelEingabe[],
    antworten_verwerfen = false,
  ) =>
    hole<Playbook>(
      `/api/playbooks/${id}/regeln${query({
        antworten_verwerfen: antworten_verwerfen ? 'true' : null,
      })}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(regeln),
      },
    ),

  playbook_loeschen: (id: number) =>
    hole<{ status: string }>(`/api/playbooks/${id}`, { method: 'DELETE' }),

  /**
   * Setzt die Regel-Antworten auf genau diese Liste.
   *
   * Was fehlt, gilt als **unbeantwortet** — nicht als „nicht eingehalten".
   */
  trade_regeln_setzen: (id: number, antworten: RegelAntwort[]) =>
    hole<Trade>(`/api/trades/${id}/regeln`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(antworten),
    }),

  regeltreue: (f: Filters & { min_sample?: number }) =>
    hole<Regeltreue>(`/api/reports/regeltreue${query({ ...f })}`),
};
