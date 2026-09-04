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
  // Die einzige Rubrik, die eine eigene Form hat: Sie vergleicht nicht
  // Gruppen von Trades, sondern das Befolgen der eigenen Regeln mit dem
  // Nichtbefolgen -- und rechnet zusätzlich je Regel ab.
  { id: 'regeltreue', label: 'Regeltreue' },
];

const BESCHRIFTUNG: Record<string, (k: string) => string> = {
  weekday: (k) => wochentag(Number(k)),
  hour: (k) => `${k}:00`,
  direction: (k) => (k === 'long' ? 'Long' : 'Short'),
};

/**
 * Die Regeltreue-Rubrik.
 *
 * Zwei Balken und eine Tabelle, und die Tabelle ist der eigentliche
 * Inhalt: Sie sagt je Regel, was ihr Bruch gekostet hat. Eine Regel,
 * deren Bruch nichts kostet, ist keine Regel — sondern eine Angewohnheit,
 * die man sich vor Jahren aufgeschrieben hat.
 */
function RegeltreueBlock({ minSample }: { minSample: number }) {
  const { filters, accountId } = useApp();
  const daten = useDaten(
    () => api.regeltreue({ ...filters, min_sample: minSample }),
    [
      minSample,
      accountId,
      filters.von,
      filters.bis,
      filters.symbol,
      filters.direction,
    ],
  );

  if (daten.fehler) return <EmptyState cause="sync" detail={daten.fehler} />;
  if (daten.laedt || !daten.daten)
    return <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>;

  const d = daten.daten;
  const bewertet = d.groups.reduce((s, g) => s + g.trades, 0);

  if (d.total_trades === 0) {
    return (
      <p
        style={{
          fontSize: 12,
          color: 'var(--td-neutral)',
          lineHeight: 1.6,
          margin: 0,
          maxWidth: 560,
        }}
      >
        Noch kein Trade mit einem Playbook. Ordne unter Trades einem Trade ein
        Playbook zu und hake die Regeln ab — hier steht dann, ob das Einhalten
        sich rechnet.
      </p>
    );
  }

  return (
    <>
      {/* Was die Zahl ist und was sie nicht ist. Beides gehört daneben:
          Kein Häkchen kommt aus MT5, jedes aus dem Kopf -- die Quote misst
          die eigene Selbsteinschätzung, nicht einen Befund. */}
      <p
        style={{
          fontSize: 11,
          color: 'var(--td-neutral)',
          margin: '0 0 12px',
          paddingLeft: 10,
          borderLeft: '2px solid var(--td-line)',
          lineHeight: 1.6,
          maxWidth: 620,
        }}
      >
        Selbstberichtet: Jedes Häkchen hast du selbst gesetzt, keins kommt aus
        MT5.{' '}
        {d.unanswered > 0 && (
          <>
            {zahl(d.unanswered)} von {zahl(d.total_trades)} Trades sind noch
            nicht vollständig durchgegangen und bleiben aus dem Vergleich
            heraus — sie zählen weder als eingehalten noch als gebrochen.
          </>
        )}
      </p>

      {bewertet > 0 ? (
        <div className="td-card">
          <ReportBars groups={d.groups} minSample={d.min_sample} />
        </div>
      ) : (
        <p style={{ fontSize: 12, color: 'var(--td-neutral)', margin: 0 }}>
          Noch keine Regel beantwortet. Am Trade stehen die Häkchen unter
          „Playbook“.
        </p>
      )}

      {d.rules.length > 0 && (
        <section className="td-section">
          <span className="td-label">Je Regel</span>
          <div className="td-scroll-x td-card" style={{ marginTop: 6 }}>
            <table>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--td-divider)' }}>
                  {[
                    'Regel',
                    'beantwortet',
                    'eingehalten',
                    'Netto wenn eingehalten',
                    'Netto wenn gebrochen',
                  ].map((h, i) => (
                    <th
                      key={h}
                      className="td-label"
                      style={{
                        padding: '6px 8px',
                        textAlign: i ? 'right' : 'left',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.rules.map((r) => (
                  <tr
                    key={r.rule_id}
                    style={{
                      borderTop: '1px solid var(--td-line)',
                      opacity: r.below_min_sample ? 0.55 : 1,
                    }}
                  >
                    <td style={{ padding: '7px 8px', minWidth: 220 }}>
                      {r.text}
                      <span
                        style={{
                          display: 'block',
                          fontSize: 10,
                          color: 'var(--td-neutral)',
                        }}
                      >
                        {r.playbook} · {r.group}
                      </span>
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {zahl(r.answered)}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {prozent(r.rate)}
                    </td>
                    <td
                      style={{
                        padding: '7px 8px',
                        textAlign: 'right',
                        color: r.kept ? undefined : 'var(--td-neutral)',
                      }}
                    >
                      {r.kept ? geld(r.pnl_kept) : '—'}
                    </td>
                    <td
                      style={{
                        padding: '7px 8px',
                        textAlign: 'right',
                        fontWeight: r.broken ? 600 : 400,
                        color: r.broken
                          ? r.pnl_broken < 0
                            ? 'var(--td-neg)'
                            : 'var(--td-pos)'
                          : 'var(--td-neutral)',
                      }}
                    >
                      {r.broken ? geld(r.pnl_broken) : '—'}
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

export default function ReportsSeite() {
  const { filters, accountId } = useApp();
  const [rubrik, setRubrik] = useState('weekday');
  const [minSample, setMinSample] = useState(8);
  const regeltreue = rubrik === 'regeltreue';

  const bericht = useDaten(
    () =>
      regeltreue
        ? Promise.resolve(null)
        : api.report(rubrik, { ...filters, min_sample: minSample }),
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
      {!regeltreue && bericht.daten?.overlapping && (
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

      {regeltreue ? (
        <div style={{ marginTop: 12 }}>
          <RegeltreueBlock minSample={minSample} />
        </div>
      ) : (
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
      )}

      {/* Datentabelle unter dem Diagramm */}
      {!regeltreue && bericht.daten && bericht.daten.groups.length > 0 && (
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
