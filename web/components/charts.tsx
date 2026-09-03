'use client';

/**
 * Die Diagramme. Alles handgezeichnetes SVG — keine Bibliothek.
 *
 * Drei Formen, drei Aufgaben:
 *   Equity-Kurve   — Verlauf über Zeit, eine Reihe (also keine Legende).
 *   Report-Balken  — Polarität: Gewinn gegen Verlust an einer Nulllinie.
 *   Score-Balken   — Größe: sechs Teilwerte auf derselben Skala.
 *
 * Farbe kommt in allen dreien aus `outcome()` und trägt nie allein die
 * Information: Es gibt immer zusätzlich ein Vorzeichen und eine Position
 * relativ zur Nulllinie.
 */

import { useId, useState } from 'react';
import { outcome } from '../lib/outcome';
import { STRICH, betrag, faktor, geld, prozent, zahl } from '../lib/format';
import type { ReportGroup } from '../lib/api';

/* ================================================================== */
/* Equity-Kurve                                                        */
/* ================================================================== */

export function EquityCurve({
  points,
  height = 190,
  currency = '€',
}: {
  points: { t: string; equity: number; drawdown: number }[];
  height?: number;
  currency?: string;
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <div
        style={{
          height,
          display: 'grid',
          placeItems: 'center',
          background: 'var(--td-sunk)',
          color: 'var(--td-neutral)',
          fontSize: 11,
        }}
      >
        Zu wenige geschlossene Trades für einen Verlauf
      </div>
    );
  }

  const B = 100; // Blickfeld-Breite; Höhe kommt aus dem Seitenverhältnis
  const H = 40;
  const pad = 2;

  const werte = points.map((p) => p.equity);
  const max = Math.max(...werte, 0);
  const min = Math.min(...werte, 0);
  const spanne = max - min || 1;

  const x = (i: number) => (i / (points.length - 1)) * B;
  const y = (v: number) => H - pad - ((v - min) / spanne) * (H - pad * 2);

  const linie = points.map((p, i) => `${x(i)},${y(p.equity)}`).join(' ');
  const flaeche = `${x(0)},${y(min)} ${linie} ${x(points.length - 1)},${y(min)}`;

  const letzter = points[points.length - 1];
  const o = outcome(letzter.equity);
  const nullLinie = y(0);

  // Drawdown-Bänder: Abschnitte, in denen die Kurve unter ihrem Hoch lag.
  const baender: { von: number; bis: number }[] = [];
  let start: number | null = null;
  points.forEach((p, i) => {
    if (p.drawdown > 0 && start === null) start = i;
    if (p.drawdown === 0 && start !== null) {
      baender.push({ von: start, bis: i });
      start = null;
    }
  });
  if (start !== null) baender.push({ von: start, bis: points.length - 1 });

  const aktiv = hover === null ? points.length - 1 : hover;

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${B} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height, display: 'block' }}
        role="img"
        aria-label={`Equity-Verlauf über ${points.length} geschlossene Trades, Endstand ${geld(
          letzter.equity,
          currency,
        )}`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const anteil = (e.clientX - box.left) / box.width;
          setHover(
            Math.max(0, Math.min(points.length - 1, Math.round(anteil * (points.length - 1)))),
          );
        }}
      >
        <defs>
          <linearGradient id={`f${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={o.cssColor} stopOpacity="0.22" />
            <stop offset="100%" stopColor={o.cssColor} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Drawdown-Bänder liegen hinter der Kurve und bleiben zurückhaltend. */}
        {baender.map((b, i) => (
          <rect
            key={i}
            x={x(b.von)}
            y={0}
            width={Math.max(0.3, x(b.bis) - x(b.von))}
            height={H}
            fill="var(--td-neg-str)"
            opacity="0.07"
          />
        ))}

        {/* Nulllinie gestrichelt — der Bezugspunkt, nicht ein Datenwert. */}
        <line
          x1="0"
          x2={B}
          y1={nullLinie}
          y2={nullLinie}
          stroke="var(--td-neutral)"
          strokeWidth="0.2"
          strokeDasharray="1 1"
          vectorEffect="non-scaling-stroke"
        />

        <polygon points={flaeche} fill={`url(#f${id})`} />
        <polyline
          points={linie}
          fill="none"
          stroke={o.cssColor}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />

        {hover !== null && (
          <line
            x1={x(aktiv)}
            x2={x(aktiv)}
            y1={0}
            y2={H}
            stroke="var(--td-accent)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            opacity="0.45"
          />
        )}
      </svg>

      {/* Betonter Endpunkt bzw. der angefahrene Punkt. */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          left: `${(aktiv / (points.length - 1)) * 100}%`,
          top: `${(y(points[aktiv].equity) / H) * 100}%`,
          width: 9,
          height: 9,
          marginLeft: -4.5,
          marginTop: -4.5,
          background: o.cssColor,
          boxShadow: '0 0 0 2px var(--td-bg)',
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 10,
          color: 'var(--td-neutral)',
          paddingTop: 6,
        }}
      >
        <span>
          {hover === null
            ? `${points.length} geschlossene Trades`
            : new Date(points[aktiv].t).toLocaleDateString('de-DE')}
        </span>
        <span style={{ color: o.cssColor, fontWeight: 600 }}>
          {geld(points[aktiv].equity, currency)}
          {points[aktiv].drawdown > 0 && (
            <span style={{ color: 'var(--td-neutral)', fontWeight: 400 }}>
              {'  '}· {betrag(points[aktiv].drawdown, currency)} unter Hoch
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

/* ================================================================== */
/* Report-Balken                                                       */
/* ================================================================== */

/**
 * Waagerechte Balken mit Nulllinie in der Mitte.
 *
 * Gruppen unter der Mindestanzahl werden gestrichelt und gedämpft und
 * tragen einen Hinweis. Das ist keine Kosmetik: „Mittwoch sieht am besten
 * aus" bei vier Trades ist Rauschen, kein Muster — und eine Oberfläche,
 * die das ungewarnt zeigt, produziert falsche Gewissheit.
 */
export function ReportBars({
  groups,
  minSample,
  labelOf,
  currency = '€',
}: {
  groups: ReportGroup[];
  minSample: number;
  labelOf?: (key: string) => string;
  currency?: string;
}) {
  if (!groups.length) {
    return (
      <div style={{ color: 'var(--td-neutral)', padding: '16px 0' }}>
        Keine Gruppen im gewählten Ausschnitt.
      </div>
    );
  }

  const max = Math.max(...groups.map((g) => Math.abs(g.net_pnl)), 1);
  const duenn = groups.filter((g) => g.below_min_sample);

  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {groups.map((g) => {
          const o = outcome(g.net_pnl);
          const anteil = Math.abs(g.net_pnl) / max;
          const positiv = g.net_pnl > 0;
          const gedaempft = g.below_min_sample;

          return (
            <div
              key={g.key}
              style={{
                display: 'grid',
                gridTemplateColumns: '92px 1fr 110px',
                alignItems: 'center',
                gap: 10,
                minHeight: 34,
                borderTop: '1px solid var(--td-line)',
                opacity: gedaempft ? 0.55 : 1,
              }}
            >
              <span style={{ fontSize: 12 }}>
                {labelOf ? labelOf(g.key) : g.key}
              </span>

              {/* Die Spur mit Nulllinie in der Mitte. */}
              <div style={{ position: 'relative', height: 16 }}>
                <div
                  aria-hidden
                  style={{
                    position: 'absolute',
                    left: '50%',
                    top: 0,
                    bottom: 0,
                    width: 1,
                    background: 'var(--td-neutral)',
                    opacity: 0.5,
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: 2,
                    bottom: 2,
                    left: positiv ? '50%' : `${50 - anteil * 50}%`,
                    width: `${anteil * 50}%`,
                    background: gedaempft ? 'transparent' : o.cssColor,
                    border: gedaempft ? `1px dashed ${o.cssColor}` : 'none',
                  }}
                />
              </div>

              <span
                style={{
                  fontSize: 12,
                  textAlign: 'right',
                  color: o.cssColor,
                  fontWeight: 600,
                }}
              >
                {geld(g.net_pnl, currency)}
                <span
                  style={{
                    color: 'var(--td-neutral)',
                    fontWeight: 400,
                    marginLeft: 6,
                  }}
                >
                  n={g.trades}
                </span>
              </span>
            </div>
          );
        })}
      </div>

      {duenn.length > 0 && (
        <p
          style={{
            marginTop: 10,
            padding: '8px 10px',
            background: 'var(--td-sunk)',
            fontSize: 11,
            color: 'var(--td-neutral)',
            borderLeft: '3px solid var(--td-neutral)',
          }}
        >
          {duenn.length === 1 ? 'Eine Gruppe liegt' : `${duenn.length} Gruppen liegen`}{' '}
          unter {minSample} Trades ({duenn.map((g) => labelOf ? labelOf(g.key) : g.key).join(', ')}).
          Das ist Rauschen, kein Muster — die Balken sind deshalb gestrichelt.
        </p>
      )}
    </div>
  );
}

/* ================================================================== */
/* Score                                                               */
/* ================================================================== */

const TEILWERT_NAMEN: Record<string, string> = {
  win_rate: 'Trefferquote',
  profit_factor: 'Profit Factor',
  win_loss_ratio: 'Gewinn/Verlust',
  recovery_factor: 'Erholung',
  drawdown_ratio: 'Drawdown',
  consistency: 'Konsistenz',
};

/**
 * Gesamtwert groß, sechs Teilwerte daneben.
 *
 * Der Sinn ist nicht die eine Zahl — die ist für sich genommen
 * nichtssagend — sondern die Aufschlüsselung: Sie zeigt, *woran* es
 * liegt. Der schwächste Teilwert wird deshalb ausdrücklich markiert.
 */
export function ScoreDisplay({
  total,
  parts,
  missing,
}: {
  total: number | null;
  parts: Record<string, number | null>;
  missing: string[];
}) {
  const eintraege = Object.entries(parts);
  const vorhanden = eintraege.filter(([, v]) => v !== null) as [string, number][];
  const schwaechster = vorhanden.length
    ? vorhanden.reduce((a, b) => (a[1] <= b[1] ? a : b))[0]
    : null;

  return (
    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
      <div style={{ minWidth: 110 }}>
        <span className="td-label">TradeDiary-Score</span>
        <div
          className="td-display"
          style={{ fontSize: 56, lineHeight: 1, marginTop: 4 }}
        >
          {total === null ? STRICH : Math.round(total)}
        </div>
        <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
          {total === null ? 'noch keine Trades' : 'von 100'}
        </span>
      </div>

      <div style={{ flex: 1, minWidth: 220 }}>
        {eintraege.map(([schluessel, wert]) => {
          const fehlt = wert === null;
          const istSchwaechster = schluessel === schwaechster;
          return (
            <div
              key={schluessel}
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 90px 42px',
                alignItems: 'center',
                gap: 8,
                minHeight: 26,
                borderTop: '1px solid var(--td-line)',
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  color: fehlt ? 'var(--td-neutral)' : 'var(--td-text)',
                  fontWeight: istSchwaechster ? 600 : 400,
                }}
              >
                {TEILWERT_NAMEN[schluessel] ?? schluessel}
                {istSchwaechster && (
                  <span
                    className="td-label"
                    style={{ marginLeft: 6, fontSize: 9 }}
                  >
                    schwächster
                  </span>
                )}
              </span>
              <div style={{ height: 6, background: 'var(--td-sunk)' }}>
                {!fehlt && (
                  <div
                    style={{
                      height: '100%',
                      width: `${wert}%`,
                      background: istSchwaechster
                        ? 'var(--td-neg)'
                        : 'var(--td-accent)',
                    }}
                  />
                )}
              </div>
              <span
                style={{
                  fontSize: 11,
                  textAlign: 'right',
                  color: fehlt ? 'var(--td-neutral)' : 'var(--td-text)',
                }}
              >
                {fehlt ? STRICH : Math.round(wert)}
              </span>
            </div>
          );
        })}

        {missing.length > 0 && (
          <p style={{ fontSize: 10, color: 'var(--td-neutral)', marginTop: 8 }}>
            Nicht bestimmbar: {missing.map((m) => TEILWERT_NAMEN[m] ?? m).join(', ')}.
            Fehlende Teilwerte ziehen den Gesamtwert nicht nach unten — sie
            werden übersprungen.
          </p>
        )}
      </div>
    </div>
  );
}

export { faktor, prozent, zahl };
