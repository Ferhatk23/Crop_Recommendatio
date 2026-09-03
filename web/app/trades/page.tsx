'use client';

/**
 * Trade-Liste — jeden einzelnen Trade finden, sortieren, vergleichen.
 */

import { useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { FilterBar, PageHead } from '../../components/Shell';
import { TradeList } from '../../components/TradeList';
import { EmptyState } from '../../components/primitives';
import { api } from '../../lib/api';
import { geld, zahl } from '../../lib/format';
import { outcome } from '../../lib/outcome';

const AUSGANG = [
  { id: '', label: 'Alle' },
  { id: 'win', label: 'Gewinner' },
  { id: 'loss', label: 'Verlierer' },
  { id: 'scratch', label: 'Scratch' },
];

export default function TradesSeite() {
  const { filters, accountId, filterAktiv, resetFilters } = useApp();
  const [ausgang, setAusgang] = useState('');
  const [offset, setOffset] = useState(0);
  const LIMIT = 50;

  const liste = useDaten(
    () => api.trades({ ...filters, limit: LIMIT, offset, outcome: ausgang || undefined }),
    [accountId, filters.von, filters.bis, filters.symbol, filters.direction, ausgang, offset],
  );
  const symbole = useDaten(() => api.symbols(accountId), [accountId]);

  const summe = liste.daten?.trades.reduce((s, t) => s + t.net_pnl, 0) ?? 0;

  return (
    <>
      <PageHead title="Trades" sub="Klick auf eine Zeile öffnet das Detail" />
      <FilterBar symbole={symbole.daten ?? []} />

      <div
        style={{
          display: 'flex',
          gap: 2,
          marginTop: 12,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        {AUSGANG.map((a) => (
          <button
            key={a.id}
            onClick={() => { setAusgang(a.id); setOffset(0); }}
            aria-pressed={ausgang === a.id}
            style={{
              padding: '0 14px',
              background: ausgang === a.id ? 'var(--td-accent)' : 'var(--td-surface)',
              color: ausgang === a.id ? 'var(--td-on-accent)' : 'var(--td-text)',
              fontWeight: ausgang === a.id ? 600 : 400,
            }}
          >
            {a.label}
          </button>
        ))}

        {/* Ergebniszeile der gefilterten Auswahl */}
        {liste.daten && (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 12,
              color: 'var(--td-neutral)',
            }}
          >
            {zahl(liste.daten.total)} Trades ·{' '}
            <span style={{ color: outcome(summe).cssColor, fontWeight: 600 }}>
              {geld(summe)}
            </span>{' '}
            auf dieser Seite
          </span>
        )}
      </div>

      <div style={{ marginTop: 12 }}>
        {liste.fehler ? (
          <EmptyState cause="sync" detail={liste.fehler} />
        ) : liste.laedt || !liste.daten ? (
          <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
        ) : liste.daten.trades.length === 0 ? (
          <EmptyState
            cause={filterAktiv || ausgang ? 'filter' : 'keine-daten'}
            action={
              (filterAktiv || ausgang) && (
                <button
                  onClick={() => { resetFilters(); setAusgang(''); setOffset(0); }}
                  style={{
                    background: 'var(--td-accent)',
                    color: 'var(--td-on-accent)',
                    padding: '0 16px',
                    fontWeight: 600,
                  }}
                >
                  Filter zurücksetzen
                </button>
              )
            }
          />
        ) : (
          <>
            <TradeList trades={liste.daten.trades} />
            {liste.daten.total > LIMIT && (
              <div
                style={{
                  display: 'flex',
                  gap: 2,
                  marginTop: 12,
                  alignItems: 'center',
                }}
              >
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                  style={{
                    padding: '0 14px',
                    background: 'var(--td-surface)',
                    opacity: offset === 0 ? 0.45 : 1,
                  }}
                >
                  ← zurück
                </button>
                <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
                  {offset + 1}–{Math.min(offset + LIMIT, liste.daten.total)} von{' '}
                  {liste.daten.total}
                </span>
                <button
                  disabled={offset + LIMIT >= liste.daten.total}
                  onClick={() => setOffset(offset + LIMIT)}
                  style={{
                    padding: '0 14px',
                    background: 'var(--td-surface)',
                    opacity: offset + LIMIT >= liste.daten.total ? 0.45 : 1,
                  }}
                >
                  weiter →
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
