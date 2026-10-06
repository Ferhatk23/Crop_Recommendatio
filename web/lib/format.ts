/**
 * Zahlen zu Text — und der Einheiten-Umschalter.
 *
 * Der Umschalter rechnet jede Zahl auf dem Screen aus *derselben*
 * Quelle um. Deshalb liefert die API Rohwerte und keine fertigen
 * Zeichenketten: Wer hier formatierte Texte bekäme, könnte nicht mehr
 * umschalten.
 *
 * Und: Jede Zahl trägt ihre Einheit. "+1.284" allein ist keine Aussage,
 * "+1.284 € · August" schon.
 */

import { outcome } from './outcome';

export type Unit = 'eur' | 'r' | 'pct' | 'pips';

export const UNITS: { id: Unit; label: string }[] = [
  { id: 'eur', label: '€' },
  { id: 'r', label: 'R' },
  { id: 'pct', label: '%' },
  { id: 'pips', label: 'Pips' },
];

const NF = (min: number, max: number) =>
  new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });

const GELD = NF(2, 2);
const ZWEI = NF(2, 2);
const EINE = NF(1, 1);
const GANZ = NF(0, 0);

/**
 * Formatierer nach Stellenzahl, zwischengespeichert.
 *
 * `Intl.NumberFormat` neu zu bauen ist teuer genug, dass es in einer
 * Tabelle mit ein paar hundert Zellen auffällt.
 */
const FORMATIERER = new Map<number, Intl.NumberFormat>([
  [0, GANZ],
  [1, EINE],
  [2, ZWEI],
]);

function mitStellen(stellen: number): Intl.NumberFormat {
  let nf = FORMATIERER.get(stellen);
  if (!nf) {
    nf = NF(stellen, stellen);
    FORMATIERER.set(stellen, nf);
  }
  return nf;
}

/** Der Strich, der überall dort steht, wo ein Wert nicht messbar ist. */
export const STRICH = '—';

/**
 * Ein Geldbetrag mit Vorzeichen und Währung.
 * `null` wird zum Strich — niemals zu "0,00 €".
 */
export function geld(value: number | null | undefined, currency = '€'): string {
  if (value === null || value === undefined) return STRICH;
  const o = outcome(value);
  return `${o.sign}${GELD.format(Math.abs(value))} ${currency}`;
}

/** Geld ohne Vorzeichen — für Limits und Beträge, die keine Richtung haben. */
export function betrag(value: number | null | undefined, currency = '€'): string {
  if (value === null || value === undefined) return STRICH;
  return `${GELD.format(value)} ${currency}`;
}

/** Ein R-Multiple: "+2,40R". */
export function rMultiple(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRICH;
  const o = outcome(value);
  return `${o.sign}${ZWEI.format(Math.abs(value))}R`;
}

/**
 * Ein Anteil 0..1 als Prozent: "58,3 %".
 *
 * `stellen` gilt genau so, wie es mitgegeben wurde. Das klingt
 * selbstverständlich, war es aber nicht: Solange nur 0 und 1 Stellen
 * gebaut wurden, lieferte der Einheiten-Umschalter für "%" stillschweigend
 * eine Stelle zu wenig -- und bei einem Tagesverlust von 1,04 % gegen ein
 * Limit von 1,00 % ist die zweite Stelle die ganze Aussage.
 */
export function prozent(
  value: number | null | undefined,
  stellen = 1,
): string {
  if (value === null || value === undefined) return STRICH;
  return `${mitStellen(stellen).format(value * 100)} %`;
}

/** Ein Verhältnis ohne Einheit: "1,84". */
export function faktor(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRICH;
  return ZWEI.format(value);
}

/** Lot-Größe: "1,50". */
export function lot(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRICH;
  return ZWEI.format(value);
}

/** Ein Preis mit der Stellenzahl, die das Instrument braucht. */
export function preis(
  value: number | null | undefined,
  digits = 5,
): string {
  if (value === null || value === undefined) return STRICH;
  return mitStellen(digits).format(value);
}

/**
 * Ein Geldbetrag ohne Nachkommastellen, mit Vorzeichen.
 *
 * Für enge Stellen -- die Kalenderzelle auf dem Telefon hat rund 50 px,
 * da sind zwei Nachkommastellen weder lesbar noch nötig: Dort zählt die
 * Größenordnung, den genauen Betrag holt man sich per Antippen.
 */
export function geldKompakt(
  value: number | null | undefined,
  currency = '',
): string {
  if (value === null || value === undefined) return STRICH;
  const o = outcome(value);
  const text = GANZ.format(Math.abs(value));
  return currency ? `${o.sign}${text} ${currency}` : `${o.sign}${text}`;
}

/** Ganze Zahl mit Tausendertrennung. */
export function zahl(value: number | null | undefined): string {
  if (value === null || value === undefined) return STRICH;
  return GANZ.format(value);
}

/**
 * Rechnet einen Euro-Betrag in die gewählte Einheit um.
 *
 * `r` und `pips` brauchen Zusatzangaben, die nicht überall vorliegen.
 * Fehlen sie, gibt die Funktion `null` zurück und die Oberfläche zeigt
 * einen Strich — statt eine Umrechnung zu erfinden.
 */
export function inEinheit(
  value: number | null | undefined,
  unit: Unit,
  ctx: { risk?: number | null; balance?: number | null; pips?: number | null } = {},
): string {
  if (value === null || value === undefined) return STRICH;

  switch (unit) {
    case 'eur':
      return geld(value);
    case 'r': {
      if (!ctx.risk) return STRICH;
      return rMultiple(value / ctx.risk);
    }
    case 'pct': {
      if (!ctx.balance) return STRICH;
      return prozent(value / ctx.balance, 2);
    }
    case 'pips': {
      if (ctx.pips === null || ctx.pips === undefined) return STRICH;
      const o = outcome(ctx.pips);
      return `${o.sign}${EINE.format(Math.abs(ctx.pips))} Pips`;
    }
  }
}

/** Dauer in lesbarer Form: "1 h 27 min". */
export function dauer(sekunden: number | null | undefined): string {
  if (sekunden === null || sekunden === undefined) return STRICH;
  const min = Math.round(sekunden / 60);
  if (min < 60) return `${min} min`;
  const std = Math.floor(min / 60);
  const rest = min % 60;
  if (std < 24) return rest ? `${std} h ${rest} min` : `${std} h`;
  const tage = Math.floor(std / 24);
  return `${tage} T ${std % 24} h`;
}

const WOCHENTAGE = [
  'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
  'Freitag', 'Samstag', 'Sonntag',
];
const WOCHENTAGE_KURZ = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const MONATE = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
];

export function wochentag(index: number, kurz = false): string {
  return (kurz ? WOCHENTAGE_KURZ : WOCHENTAGE)[index] ?? String(index);
}

export function monatsname(index1: number): string {
  return MONATE[index1 - 1] ?? String(index1);
}

/** "Mo, 02.03." */
export function tagKurz(iso: string): string {
  const d = new Date(iso);
  return `${WOCHENTAGE_KURZ[(d.getUTCDay() + 6) % 7]}, ${String(
    d.getUTCDate(),
  ).padStart(2, '0')}.${String(d.getUTCMonth() + 1).padStart(2, '0')}.`;
}

/** "02.03.2026 09:31" */
export function zeitpunkt(iso: string | null | undefined): string {
  if (!iso) return STRICH;
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())}.${p(d.getUTCMonth() + 1)}.${d.getUTCFullYear()} ${p(
    d.getUTCHours(),
  )}:${p(d.getUTCMinutes())}`;
}

/** "09:31" */
export function uhrzeit(iso: string | null | undefined): string {
  if (!iso) return STRICH;
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
