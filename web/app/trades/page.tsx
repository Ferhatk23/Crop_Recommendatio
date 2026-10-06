'use client';

/**
 * Trade-Liste — jeden einzelnen Trade finden, sortieren, vergleichen.
 */

import { useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { FilterBar, PageHead } from '../../components/Shell';
import { TradeList } from '../../components/TradeList';
import { EmptyState } from '../../components/primitives';
import { NACHARBEIT, api, type Nacharbeit } from '../../lib/api';
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
  const [nacharbeit, setNacharbeit] = useState<Nacharbeit | ''>('');
  const [offset, setOffset] = useState(0);
  const LIMIT = 50;

  const liste = useDaten(
    () =>
      api.trades({
        ...filters,
        limit: LIMIT,
        offset,
        outcome: ausgang || undefined,
        nachbearbeitung: nacharbeit || undefined,
      }),
    [
      accountId,
      filters.von,
      filters.bis,
      filters.symbol,
      filters.direction,
      ausgang,
      nacharbeit,
      offset,
    ],
  );
  const symbole = useDaten(() => api.symbols(accountId), [accountId]);

  // Wie viele noch niemand angesehen hat. Eine eigene, sehr kleine
  // Anfrage (`limit=1` — es zählt nur `total`), weil der Hinweis sonst
  // erst erschiene, nachdem man den Filter gewählt hat. Genau umgekehrt
  // soll er wirken: Er ist die Erinnerung, dass da noch was liegt.
  const unberuehrt = useDaten(
    () => api.trades({ account_id: accountId, limit: 1, nachbearbeitung: 'unberuehrt' }),
    [accountId, nacharbeit],
  );

  const summe = liste.daten?.trades.reduce((s, t) => s + t.net_pnl, 0) ?? 0;
  const offeneAnzahl = unberuehrt.daten?.total ?? 0;

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

        <select
          aria-label="Nachbearbeitung"
          value={nacharbeit}
          onChange={(e) => {
            setNacharbeit(e.target.value as Nacharbeit | '');
            setOffset(0);
          }}
          style={{ marginLeft: 8 }}
        >
          {NACHARBEIT.map((n) => (
            <option key={n.id} value={n.id}>
              {n.label}
            </option>
          ))}
        </select>

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

      {/* Der Hinweis steht auch dann da, wenn der Filter auf „alle" steht --
          sonst fände ihn nur, wer ohnehin schon danach sucht. Er
          verschwindet, sobald nichts mehr offen ist; eine dauerhafte Null
          wäre eine Mahnung ohne Anlass. */}
      {nacharbeit === '' && offeneAnzahl > 0 && (
        <div style={{ marginTop: 10 }}>
          <button
            onClick={() => {
              setNacharbeit('unberuehrt');
              setOffset(0);
            }}
            style={{
              fontSize: 11,
              color: 'var(--td-neutral)',
              borderLeft: '2px solid var(--td-line)',
              paddingLeft: 10,
              minHeight: 32,
              textAlign: 'left',
            }}
          >
            {zahl(offeneAnzahl)} {offeneAnzahl === 1 ? 'Trade' : 'Trades'} noch nicht
            angesehen — weder Notiz noch Tag noch Playbook.{' '}
            <span style={{ textDecoration: 'underline' }}>anzeigen</span>
          </button>
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        {liste.fehler ? (
          <EmptyState cause="sync" detail={liste.fehler} />
        ) : liste.laedt || !liste.daten ? (
          <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
        ) : liste.daten.trades.length === 0 ? (
          <EmptyState
            cause={filterAktiv || ausgang || nacharbeit ? 'filter' : 'keine-daten'}
            action={
              (filterAktiv || ausgang || nacharbeit) && (
                <button
                  onClick={() => {
                    resetFilters();
                    setAusgang('');
                    setNacharbeit('');
                    setOffset(0);
                  }}
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
