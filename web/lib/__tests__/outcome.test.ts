/**
 * Tests für die Ergebnis-Regel und die Formatierung.
 *
 * `outcome()` ist der Vertrag, an dem die beiden wichtigsten Design-Regeln
 * hängen: Grün und Rot gehören dem Ergebnis, und Farbe ist nie der einzige
 * Kanal. Wenn diese Funktion driftet, driftet die ganze Oberfläche mit --
 * und zwar unsichtbar, weil jede einzelne Ansicht für sich plausibel aussieht.
 */

import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';

// Ohne Endung -- genau wie der Anwendungscode. Node bekommt die Endung
// über den Auflöser in `tools/ts-resolve.mjs` nachgereicht.
import { outcome, outcomeClass } from '../outcome';
import {
  STRICH,
  betrag,
  dauer,
  faktor,
  geld,
  geldKompakt,
  inEinheit,
  lot,
  preis,
  prozent,
  rMultiple,
  zahl,
} from '../format';

describe('outcome()', () => {
  it('gibt Gewinnen ein Plus, die obere Regel und Grün', () => {
    const o = outcome(245);
    assert.equal(o.sign, '+');
    assert.equal(o.color, 'pos');
    assert.equal(o.rule, 'top');
    assert.equal(o.ruleClass, 'td-rule-top');
    assert.equal(o.cssColor, 'var(--td-pos)');
    assert.equal(o.empty, false);
  });

  it('gibt Verlusten ein Minus, die untere Regel und Rot', () => {
    const o = outcome(-165);
    assert.equal(o.sign, '−'); // echtes Minuszeichen, kein Bindestrich
    assert.equal(o.color, 'neg');
    assert.equal(o.rule, 'bottom');
    assert.equal(o.ruleClass, 'td-rule-bottom');
  });

  it('behandelt die Null als Ergebnis, nicht als fehlenden Wert', () => {
    const o = outcome(0);
    assert.equal(o.sign, '±');
    assert.equal(o.color, 'neutral');
    assert.equal(o.rule, 'none');
    assert.equal(o.empty, false, 'genau ausgegangen ist ein Ergebnis');
  });

  it('verlangt bei fehlendem Wert einen Grund', () => {
    for (const wert of [null, undefined, NaN]) {
      const o = outcome(wert as number | null, 'kein Stop erfasst');
      assert.equal(o.empty, true);
      assert.equal(o.reason, 'kein Stop erfasst');
      assert.equal(o.sign, '');
      assert.equal(o.color, 'neutral');
    }
  });

  it('setzt einen Standardgrund, wenn keiner mitgegeben wurde', () => {
    // Lieber ein unscharfer Grund als gar keiner -- die Oberfläche soll
    // niemals eine leere Stelle ohne Erklärung zeigen.
    assert.equal(outcome(null).reason, 'nicht messbar');
  });

  it('liefert für jedes Vorzeichen einen eigenen zweiten Kanal', () => {
    // Der Kern von Regel 2: Wer nur die Farbe sieht, verliert nichts,
    // weil Vorzeichen und Regelposition dieselbe Information tragen.
    const werte = [5, -5, 0];
    const zeichen = new Set(werte.map((w) => outcome(w).sign));
    const regeln = new Set(werte.map((w) => outcome(w).rule));
    assert.equal(zeichen.size, 3, 'drei unterscheidbare Vorzeichen');
    assert.equal(regeln.size, 3, 'drei unterscheidbare Regelpositionen');
  });

  it('outcomeClass passt zur Farbe', () => {
    assert.equal(outcomeClass(1), 'td-pos');
    assert.equal(outcomeClass(-1), 'td-neg');
    assert.equal(outcomeClass(0), 'td-neutral');
    assert.equal(outcomeClass(null), 'td-neutral');
  });
});

describe('Formatierung', () => {
  it('setzt Geld deutsch, mit Vorzeichen und Währung', () => {
    assert.equal(geld(1284.5), '+1.284,50 €');
    assert.equal(geld(-165), '−165,00 €');
    assert.equal(geld(0), '±0,00 €');
  });

  it('macht aus einem fehlenden Wert einen Strich, niemals eine Null', () => {
    // Der wichtigste Test hier: "0,00 €" wäre eine Behauptung über ein
    // Ergebnis, das es nicht gibt.
    assert.equal(geld(null), STRICH);
    assert.equal(rMultiple(null), STRICH);
    assert.equal(prozent(null), STRICH);
    assert.equal(faktor(null), STRICH);
    assert.equal(lot(null), STRICH);
    assert.equal(preis(null), STRICH);
    assert.equal(zahl(null), STRICH);
    assert.equal(betrag(null), STRICH);
    assert.equal(geldKompakt(null), STRICH);
    assert.equal(dauer(null), STRICH);
  });

  it('führt Beträge ohne Richtung ohne Vorzeichen', () => {
    // Ein Limit ist kein Ergebnis -- "+5.000,00 €" wäre irreführend.
    assert.equal(betrag(5000), '5.000,00 €');
  });

  it('setzt R-Multiples mit zwei Stellen', () => {
    assert.equal(rMultiple(2.4), '+2,40R');
    assert.equal(rMultiple(-1), '−1,00R');
  });

  it('setzt Prozente aus einem Anteil', () => {
    assert.equal(prozent(0.583), '58,3 %');
    assert.equal(prozent(0.4, 0), '40 %');
  });

  it('hält sich an die verlangte Stellenzahl', () => {
    // War lange falsch: gebaut waren nur 0 und 1 Stelle, alles andere
    // fiel stillschweigend auf eine zurück. Gegen ein Limit von 1,00 %
    // ist der Unterschied zwischen 1,0 % und 1,04 % die ganze Aussage.
    assert.equal(prozent(0.0104, 2), '1,04 %');
    assert.equal(prozent(0.5, 3), '50,000 %');
  });

  it('kürzt kompakte Beträge ohne Nachkommastellen', () => {
    assert.equal(geldKompakt(3004.62), '+3.005');
    assert.equal(geldKompakt(-2148.35, '€'), '−2.148 €');
  });

  it('setzt Preise mit der Stellenzahl des Instruments', () => {
    assert.equal(preis(1.0842, 5), '1,08420');
    assert.equal(preis(2420, 2), '2.420,00');
  });

  it('schreibt Dauern lesbar', () => {
    assert.equal(dauer(47 * 60), '47 min');
    assert.equal(dauer(90 * 60), '1 h 30 min');
    assert.equal(dauer(3 * 3600), '3 h');
    assert.equal(dauer(30 * 3600), '1 T 6 h');
  });
});

describe('Einheiten-Umschalter', () => {
  it('rechnet aus derselben Quelle um', () => {
    assert.equal(inEinheit(245, 'eur'), '+245,00 €');
    assert.equal(inEinheit(245, 'r', { risk: 100 }), '+2,45R');
    assert.equal(inEinheit(1000, 'pct', { balance: 100000 }), '1,00 %');
  });

  it('erfindet keine Umrechnung, wenn die Bezugsgröße fehlt', () => {
    // Ohne Risiko gibt es kein R. Ein geschätztes R wäre schlimmer als
    // ein Strich, weil man es nicht als Schätzung erkennt.
    assert.equal(inEinheit(245, 'r', {}), STRICH);
    assert.equal(inEinheit(245, 'r', { risk: 0 }), STRICH);
    assert.equal(inEinheit(245, 'pct', {}), STRICH);
    assert.equal(inEinheit(245, 'pips', {}), STRICH);
  });

  it('bleibt bei fehlendem Ausgangswert beim Strich', () => {
    for (const einheit of ['eur', 'r', 'pct', 'pips'] as const) {
      assert.equal(inEinheit(null, einheit, { risk: 100, balance: 1000 }), STRICH);
    }
  });
});
