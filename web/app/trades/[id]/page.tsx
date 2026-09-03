'use client';

/**
 * Trade-Detail — einen einzelnen Trade verstehen.
 *
 * Statt eines Kurs-Charts steht hier ein Ausführungsverlauf: die
 * einzelnen Teilkäufe und -verkäufe auf einer Zeit- und Preisachse, aus
 * unseren eigenen Daten gezeichnet. Historische Kursdaten kosten Geld
 * und sind mit dem Backtesting gestrichen worden — das Wesentliche zeigt
 * der Verlauf trotzdem: ob gestaffelt eingestiegen wurde und ob der
 * Ausstieg früh kam.
 */

import { use } from 'react';
import Link from 'next/link';
import { useDaten } from '../../../components/AppState';
import { PageHead } from '../../../components/Shell';
import {
  DirectionPill,
  EmptyState,
  TagChip,
} from '../../../components/primitives';
import { api, type Execution } from '../../../lib/api';
import { outcome } from '../../../lib/outcome';
import {
  STRICH,
  betrag,
  dauer,
  geld,
  lot,
  preis,
  rMultiple,
  zeitpunkt,
} from '../../../lib/format';

function Ausfuehrungsverlauf({
  executions,
  entry,
  exit,
  stop,
}: {
  executions: Execution[];
  entry: number | null;
  exit: number | null;
  stop: number | null;
}) {
  if (executions.length < 2) return null;

  const zeiten = executions.map((e) => new Date(e.time).getTime());
  const preise = executions.map((e) => e.price);
  const alle = stop !== null ? [...preise, stop] : preise;

  const tMin = Math.min(...zeiten);
  const tMax = Math.max(...zeiten);
  const pMin = Math.min(...alle);
  const pMax = Math.max(...alle);
  const tSpanne = tMax - tMin || 1;
  const pSpanne = pMax - pMin || 1;

  const B = 100;
  const H = 44;
  const pad = 4;
  const x = (t: number) => ((t - tMin) / tSpanne) * (B - pad * 2) + pad;
  const y = (p: number) => H - pad - ((p - pMin) / pSpanne) * (H - pad * 2);

  return (
    <div>
      <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${B} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: 170, display: 'block' }}
        role="img"
        aria-label={`Ausführungsverlauf mit ${executions.length} Teilausführungen`}
      >
        {/* Stop als gestrichelte Linie — ein Bezugswert, kein Datenpunkt. */}
        {stop !== null && (
          <line
            x1={0}
            x2={B}
            y1={y(stop)}
            y2={y(stop)}
            stroke="var(--td-neg-str)"
            strokeWidth="1"
            strokeDasharray="2 2"
            vectorEffect="non-scaling-stroke"
            opacity="0.7"
          />
        )}
        {entry !== null && (
          <line
            x1={0}
            x2={B}
            y1={y(entry)}
            y2={y(entry)}
            stroke="var(--td-neutral)"
            strokeWidth="1"
            strokeDasharray="1 2"
            vectorEffect="non-scaling-stroke"
          />
        )}

        <polyline
          points={executions.map((e) => `${x(new Date(e.time).getTime())},${y(e.price)}`).join(' ')}
          fill="none"
          stroke="var(--td-accent)"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
          opacity="0.4"
        />

      </svg>

      {/* Die Marken liegen als HTML über dem SVG. Im gestreckten
          Koordinatensystem würde ein Quadrat zum Rechteck und ein Kreis
          zur Ellipse — hier bleiben sie rund und quadratisch, und sie
          sind mit 9 px auch groß genug, um sie zu treffen. */}
      {executions.map((e) => {
        const rein = e.entry === 'in';
        const links = (x(new Date(e.time).getTime()) / B) * 100;
        const oben = (y(e.price) / H) * 100;
        return (
          <span
            key={e.ticket}
            aria-hidden
            title={`${rein ? 'Einstieg' : 'Ausstieg'} ${e.volume} @ ${e.price}`}
            style={{
              position: 'absolute',
              left: `${links}%`,
              top: `${oben}%`,
              width: 9,
              height: 9,
              marginLeft: -4.5,
              marginTop: -4.5,
              background: rein ? 'var(--td-accent)' : 'var(--td-bg)',
              border: rein ? 'none' : '2px solid var(--td-accent)',
              borderRadius: rein ? 0 : '50%',
            }}
          />
        );
      })}

      </div>

      <div
        style={{
          display: 'flex',
          gap: 16,
          fontSize: 10,
          color: 'var(--td-neutral)',
          paddingTop: 6,
          flexWrap: 'wrap',
        }}
      >
        <span>■ Einstieg</span>
        <span>○ Ausstieg</span>
        {stop !== null && (
          <span style={{ color: 'var(--td-neg)' }}>--- Stop</span>
        )}
        <span style={{ marginLeft: 'auto' }}>Zeit →</span>
      </div>
    </div>
  );
}

function Kennwert({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div
      style={{
        padding: '10px 12px',
        background: 'var(--td-surface)',
        minHeight: 62,
      }}
    >
      <span className="td-label">{label}</span>
      <div style={{ fontSize: 15, fontWeight: 600, color: color ?? 'inherit' }}>
        {value}
      </div>
      {hint && (
        <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>{hint}</span>
      )}
    </div>
  );
}

export default function TradeDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const trade = useDaten(() => api.trade(Number(id)), [id]);

  if (trade.fehler) {
    return (
      <>
        <PageHead title="Trade" />
        <EmptyState cause="sync" detail={trade.fehler} />
      </>
    );
  }
  if (trade.laedt || !trade.daten) {
    return (
      <>
        <PageHead title="Trade" />
        <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
      </>
    );
  }

  const t = trade.daten;
  const o = outcome(t.net_pnl);

  return (
    <>
      <Link
        href="/trades"
        style={{ fontSize: 11, color: 'var(--td-neutral)' }}
        className="td-tap"
      >
        ← zurück zur Liste
      </Link>

      {/* Kopfzeile */}
      <div
        className={o.ruleClass}
        style={{
          background: 'var(--td-surface)',
          padding: '16px 18px 18px',
          marginTop: 8,
          display: 'flex',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
          alignItems: 'flex-start',
        }}
      >
        <div>
          <div
            style={{ display: 'flex', gap: 10, alignItems: 'center' }}
          >
            <h1 className="td-display" style={{ fontSize: 26, margin: 0 }}>
              {t.symbol}
            </h1>
            <DirectionPill direction={t.direction} />
            {t.partial && (
              <span
                className="td-label"
                style={{ color: 'var(--td-neg)', fontSize: 9 }}
                title="Die Eröffnung lag vor dem abgefragten Zeitraum"
              >
                Bruchstück
              </span>
            )}
          </div>
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            {zeitpunkt(t.opened_at)}
            {t.closed_at ? ` → ${zeitpunkt(t.closed_at)}` : ' · noch offen'}
            {' · '}
            {dauer(t.duration_seconds)}
          </span>
        </div>

        <div style={{ textAlign: 'right' }}>
          <div
            className="td-display"
            style={{ fontSize: 38, color: o.cssColor }}
          >
            {geld(t.net_pnl)}
          </div>
          <span
            style={{
              fontSize: 12,
              color: t.r_multiple === null ? 'var(--td-neutral)' : o.cssColor,
            }}
            title={t.r_multiple === null ? 'kein Stop erfasst' : undefined}
          >
            {rMultiple(t.r_multiple)}
            {t.r_multiple === null && ' · kein Stop erfasst'}
          </span>
        </div>
      </div>

      {/* Kennzahlen */}
      <div className="td-grid td-grid-4" style={{ marginTop: 2 }}>
        <Kennwert label="Volumen" value={`${lot(t.volume)} Lot`} />
        <Kennwert
          label="Einstieg"
          value={t.avg_entry === null ? STRICH : preis(t.avg_entry, t.digits)}
          hint={t.partial ? 'vor dem Zeitraum' : 'gewichtetes Mittel'}
        />
        <Kennwert
          label="Ausstieg"
          value={t.avg_exit === null ? STRICH : preis(t.avg_exit, t.digits)}
          hint={t.is_open ? 'noch offen' : 'gewichtetes Mittel'}
        />
        <Kennwert
          label="Stop"
          value={t.initial_sl === null ? STRICH : preis(t.initial_sl, t.digits)}
          hint={t.risk_amount ? `Risiko ${betrag(t.risk_amount)}` : 'nicht erfasst'}
        />
      </div>
      <div className="td-grid td-grid-3" style={{ marginTop: 2 }}>
        <Kennwert
          label="Brutto"
          value={geld(t.gross_pnl)}
          color={outcome(t.gross_pnl).cssColor}
        />
        <Kennwert
          label="Kosten"
          value={geld(t.costs)}
          hint="Kommission, Swap, Gebühren"
          color={outcome(t.costs).cssColor}
        />
        <Kennwert
          label="Netto"
          value={geld(t.net_pnl)}
          hint="Brutto abzüglich Kosten"
          color={o.cssColor}
        />
      </div>

      {/* Ausführungsverlauf */}
      <section className="td-section">
        <span className="td-label">Ausführungsverlauf</span>
        <div className="td-card" style={{ marginTop: 6 }}>
          <Ausfuehrungsverlauf
            executions={t.executions}
            entry={t.avg_entry}
            exit={t.avg_exit}
            stop={t.initial_sl}
          />
        </div>
      </section>

      {/* Ausführungstabelle */}
      <section className="td-section">
        <span className="td-label">
          Ausführungen · {t.executions.length}
        </span>
        <div className="td-scroll-x td-card" style={{ marginTop: 6 }}>
          <table>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--td-divider)' }}>
                {['Zeit', 'Seite', '', 'Lot', 'Preis', 'Ergebnis', 'Kommission', 'Swap'].map(
                  (h, i) => (
                    <th
                      key={i}
                      className="td-label"
                      style={{
                        padding: '6px 8px',
                        textAlign: i >= 3 ? 'right' : 'left',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {t.executions.map((e) => (
                <tr key={e.ticket} style={{ borderTop: '1px solid var(--td-line)' }}>
                  <td style={{ padding: '7px 8px', whiteSpace: 'nowrap' }}>
                    {zeitpunkt(e.time)}
                  </td>
                  <td style={{ padding: '7px 8px' }}>{e.type}</td>
                  <td style={{ padding: '7px 8px', color: 'var(--td-neutral)' }}>
                    {e.entry === 'in' ? 'ein' : e.entry === 'out' ? 'aus' : e.entry}
                  </td>
                  <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                    {lot(e.volume)}
                  </td>
                  <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                    {preis(e.price, t.digits)}
                  </td>
                  <td
                    style={{
                      padding: '7px 8px',
                      textAlign: 'right',
                      color: e.profit ? outcome(e.profit).cssColor : 'var(--td-neutral)',
                    }}
                  >
                    {e.profit ? geld(e.profit) : STRICH}
                  </td>
                  <td
                    style={{
                      padding: '7px 8px',
                      textAlign: 'right',
                      color: 'var(--td-neutral)',
                    }}
                  >
                    {geld(e.commission)}
                  </td>
                  <td
                    style={{
                      padding: '7px 8px',
                      textAlign: 'right',
                      color: 'var(--td-neutral)',
                    }}
                  >
                    {e.swap ? geld(e.swap) : STRICH}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Tags */}
      <section className="td-section">
        <span className="td-label">Tags</span>
        <div
          style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}
        >
          {t.tags.length ? (
            t.tags.map((tag) => <TagChip key={tag.id} tag={tag} />)
          ) : (
            <span style={{ color: 'var(--td-neutral)', fontSize: 12 }}>
              Noch keine Tags vergeben.
            </span>
          )}
        </div>
      </section>

      {/* Notiz */}
      <section className="td-section">
        <span className="td-label">Notiz</span>
        <div className="td-card" style={{ marginTop: 6 }}>
          {t.note ? (
            <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{t.note}</p>
          ) : (
            <span style={{ color: 'var(--td-neutral)', fontSize: 12 }}>
              Noch keine Notiz zu diesem Trade.
            </span>
          )}
        </div>
      </section>
    </>
  );
}
