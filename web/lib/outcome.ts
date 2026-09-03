/**
 * Die eine Quelle für jede Ergebnisdarstellung.
 *
 * Regel 1 und 2 des Designsystems im Code: Vorzeichen, Farbe und
 * Regelposition kommen aus derselben Funktion. Keine Komponente
 * entscheidet das selbst — sonst driften die Darstellungen
 * auseinander und irgendwo steht am Ende ein grüner Verlust.
 *
 * Wichtig: `0` bedeutet "genau ausgegangen", nicht "keine Daten".
 * Für nicht existierende Kennzahlen ist `null` vorgesehen, und dann
 * verlangt die Funktion einen Grund — eine Null, die wie ein Ergebnis
 * aussieht, ist die gefährlichste aller Antworten.
 */

export type OutcomeColor = 'pos' | 'neg' | 'neutral';
export type RulePosition = 'top' | 'bottom' | 'none';

export interface Outcome {
  /** '+' | '−' | '±' | '' — der zweite Kanal neben der Farbe. */
  sign: string;
  color: OutcomeColor;
  /** Rahmenposition: oben = Gewinn, unten = Verlust. Dritter Kanal. */
  rule: RulePosition;
  /** CSS-Variable für Text. */
  cssColor: string;
  /** CSS-Variable für Flächen. */
  cssTint: string;
  /** Klassenname für die Regelposition. */
  ruleClass: string;
  /** Nur gesetzt, wenn kein Wert vorliegt — dann Pflicht. */
  reason?: string;
  /** true, wenn gar kein Wert vorliegt. */
  empty: boolean;
}

const LEER: Omit<Outcome, 'reason'> = {
  sign: '',
  color: 'neutral',
  rule: 'none',
  cssColor: 'var(--td-neutral)',
  cssTint: 'var(--td-neutral-t)',
  ruleClass: 'td-rule-none',
  empty: true,
};

/**
 * @param value  Der Ergebniswert, oder `null`, wenn es keinen gibt.
 * @param reason Warum es keinen gibt. Pflicht, wenn `value` null ist.
 */
export function outcome(
  value: number | null | undefined,
  reason?: string,
): Outcome {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return {
      ...LEER,
      reason: reason ?? 'nicht messbar',
    };
  }

  const pos = value > 0;
  const neg = value < 0;

  return {
    sign: pos ? '+' : neg ? '−' : '±',
    color: pos ? 'pos' : neg ? 'neg' : 'neutral',
    rule: pos ? 'top' : neg ? 'bottom' : 'none',
    cssColor: pos
      ? 'var(--td-pos)'
      : neg
        ? 'var(--td-neg)'
        : 'var(--td-neutral)',
    cssTint: pos
      ? 'var(--td-pos-tint)'
      : neg
        ? 'var(--td-neg-tint)'
        : 'var(--td-neutral-t)',
    ruleClass: pos
      ? 'td-rule-top'
      : neg
        ? 'td-rule-bottom'
        : 'td-rule-none',
    empty: false,
  };
}

/** Die Klasse für Textfarbe, passend zum Ergebnis. */
export function outcomeClass(value: number | null | undefined): string {
  const o = outcome(value);
  return o.color === 'pos'
    ? 'td-pos'
    : o.color === 'neg'
      ? 'td-neg'
      : 'td-neutral';
}
