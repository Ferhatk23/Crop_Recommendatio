'use client';

/**
 * Reports — unter welchen Bedingungen verdiene ich Geld?
 *
 * Sechs Rubriken, ein Bauteil: Jede ist dieselbe Gruppierung über eine
 * andere Spalte. Deshalb kostet die Breite hier fast nichts, sobald das
 * Bauteil einmal steht.
 */

import { useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { FilterBar, PageHead } from '../../components/Shell';
import { ReportBars } from '../../components/charts';
import { EmptyState } from '../../components/primitives';
import { api } from '../../lib/api';
import { faktor, geld, prozent, wochentag, zahl } from '../../lib/format';

const RUBRIKEN = [
  { id: 'weekday', label: 'Wochentag' },
  { id: 'hour', label: 'Uhrzeit' },
  { id: 'symbol', label: 'Instrument' },
  { id: 'duration', label: 'Haltedauer' },
  { id: 'volume', label: 'Lot-Größe' },
  { id: 'direction', label: 'Seite' },
  // Die drei Rubriken, für die man überhaupt taggt. Alles darüber
  // beschreibt den Markt, das hier beschreibt den Händler.
  { id: 'setup', label: 'Setup' },
  { id: 'fehler', label: 'Fehler' },
  { id: 'emotion', label: 'Verfassung' },
];

const BESCHRIFTUNG: Record<string, (k: string) => string> = {
  weekday: (k) => wochentag(Number(k)),
  hour: (k) => `${k}:00`,
  direction: (k) => (k === 'long' ? 'Long' : 'Short'),
};

export default function ReportsSeite() {
  const { filters, accountId } = useApp();
  const [rubrik, setRubrik] = useState('weekday');
  const [minSample, setMinSample] = useState(8);

  const bericht = useDaten(
    () => api.report(rubrik, { ...filters, min_sample: minSample }),
    [rubrik, minSample, accountId, filters.von, filters.bis, filters.symbol, filters.direction],
  );
  const symbole = useDaten(() => api.symbols(accountId), [accountId]);

  return (
    <>
      <PageHead
        title="Reports"
        sub="Gruppen unter der Mindestanzahl sind gestrichelt — das ist Rauschen, kein Muster"
      />
      <FilterBar symbole={symbole.daten ?? []} />

      <div style={{ display: 'flex', gap: 2, marginTop: 12, flexWrap: 'wrap' }}>
        {RUBRIKEN.map((r) => (
          <button
            key={r.id}
            onClick={() => setRubrik(r.id)}
            aria-pressed={rubrik === r.id}
            style={{
              padding: '0 14px',
              background: rubrik === r.id ? 'var(--td-accent)' : 'var(--td-surface)',
              color: rubrik === r.id ? 'var(--td-on-accent)' : 'var(--td-text)',
              fontWeight: rubrik === r.id ? 600 : 400,
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          gap: 10,
          alignItems: 'center',
          marginTop: 12,
          flexWrap: 'wrap',
        }}
      >
        <label htmlFor="mins" className="td-label">
          Mindestanzahl je Gruppe
        </label>
        <input
          id="mins"
          type="number"
          min={1}
          max={100}
          value={minSample}
          onChange={(e) => setMinSample(Math.max(1, Number(e.target.value) || 1))}
          style={{ width: 80 }}
        />
      </div>

      {/* Bei Tag-Rubriken zählt ein Trade in mehreren Gruppen -- und
          Trades ohne Tag bilden eine eigene. Beides muss dastehen: Wer
          die Gruppen zusammenzählt, käme sonst auf mehr Trades als es
          gibt, und wer die Gruppe "ohne" übersieht, hält eine Aussage
          über den beschrifteten Teil für eine über alle. */}
      {bericht.daten?.overlapping && (
        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            margin: '10px 0 0',
            paddingLeft: 10,
            borderLeft: '2px solid var(--td-line)',
          }}
        >
          Ein Trade kann mehrere Tags tragen und zählt dann in mehreren
          Gruppen — die Gruppen ergeben zusammen mehr als die{' '}
          {zahl(bericht.daten.total_trades)} Trades. Nicht beschriftete Trades
          stehen unter „ohne“; sie gehören zum Bild, sonst beschreibt der
          Report nur den Teil, den du schon eingeordnet hast.
        </p>
      )}

      <div className="td-card" style={{ marginTop: 12 }}>
        {bericht.fehler ? (
          <EmptyState cause="sync" detail={bericht.fehler} />
        ) : bericht.laedt || !bericht.daten ? (
          <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
        ) : bericht.daten.groups.length === 0 ? (
          <EmptyState cause="filter" />
        ) : (
          <ReportBars
            groups={bericht.daten.groups}
            minSample={bericht.daten.min_sample}
            labelOf={BESCHRIFTUNG[rubrik]}
          />
        )}
      </div>

      {/* Datentabelle unter dem Diagramm */}
      {bericht.daten && bericht.daten.groups.length > 0 && (
        <section className="td-section">
          <span className="td-label">Zahlen zur Grafik</span>
          <div className="td-scroll-x td-card" style={{ marginTop: 6 }}>
            <table>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--td-divider)' }}>
                  {['Gruppe', 'Trades', 'Netto', 'Trefferquote', 'Profit Factor', 'Erwartung'].map(
                    (h, i) => (
                      <th
                        key={h}
                        className="td-label"
                        style={{ padding: '6px 8px', textAlign: i ? 'right' : 'left' }}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {bericht.daten.groups.map((g) => (
                  <tr
                    key={g.key}
                    style={{
                      borderTop: '1px solid var(--td-line)',
                      opacity: g.below_min_sample ? 0.55 : 1,
                    }}
                  >
                    <td style={{ padding: '7px 8px' }}>
                      {BESCHRIFTUNG[rubrik] ? BESCHRIFTUNG[rubrik](g.key) : g.key}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {zahl(g.trades)}
                    </td>
                    <td
                      style={{
                        padding: '7px 8px',
                        textAlign: 'right',
                        fontWeight: 600,
                        color: g.net_pnl > 0 ? 'var(--td-pos)' : g.net_pnl < 0 ? 'var(--td-neg)' : 'var(--td-neutral)',
                      }}
                    >
                      {geld(g.net_pnl)}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {prozent(g.win_rate)}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {faktor(g.profit_factor)}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {geld(g.expectancy)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
