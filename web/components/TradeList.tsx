'use client';

/**
 * Die Trade-Liste — die dichteste Fläche im Produkt.
 *
 * Auf breiten Schirmen eine Tabelle, auf dem Telefon Karten. Das ist
 * keine Notlösung: Eine achtspaltige Tabelle auf 390 px zwingt zum
 * seitlichen Scrollen, und dann vergleicht man nichts mehr.
 *
 * Die Standardspalten sind bewusst gewählt — welche acht *ohne*
 * Konfiguration sichtbar sind, entscheidet, ob der Screen benutzbar ist.
 */

import Link from 'next/link';
import type { Trade } from '../lib/api';
import { outcome } from '../lib/outcome';
import { DirectionPill, TagChip } from './primitives';
import {
  STRICH,
  dauer,
  geld,
  lot,
  preis,
  rMultiple,
  tagKurz,
  uhrzeit,
} from '../lib/format';

function Zeile({ trade }: { trade: Trade }) {
  const o = outcome(trade.net_pnl);
  return (
    <tr
      style={{
        borderTop: '1px solid var(--td-line)',
        borderLeft: `3px solid ${
          trade.outcome === 'win'
            ? 'var(--td-pos)'
            : trade.outcome === 'loss'
              ? 'var(--td-neg-str)'
              : 'var(--td-neutral)'
        }`,
      }}
    >
      <td style={{ padding: '9px 10px', whiteSpace: 'nowrap' }}>
        <Link href={`/trades/${trade.id}`} style={{ display: 'block' }}>
          <span>{tagKurz(trade.opened_at ?? '')}</span>{' '}
          <span style={{ color: 'var(--td-neutral)', fontSize: 11 }}>
            {uhrzeit(trade.opened_at)}
          </span>
        </Link>
      </td>
      <td style={{ padding: '9px 10px', fontWeight: 600 }}>
        <Link href={`/trades/${trade.id}`}>{trade.symbol}</Link>
      </td>
      <td style={{ padding: '9px 10px' }}>
        <DirectionPill direction={trade.direction} />
      </td>
      <td style={{ padding: '9px 10px', textAlign: 'right' }}>
        {lot(trade.volume)}
      </td>
      <td
        style={{
          padding: '9px 10px',
          textAlign: 'right',
          color: 'var(--td-neutral)',
        }}
      >
        {trade.avg_entry === null ? STRICH : preis(trade.avg_entry, trade.digits)}
      </td>
      <td
        style={{
          padding: '9px 10px',
          textAlign: 'right',
          color: 'var(--td-neutral)',
        }}
      >
        {trade.avg_exit === null ? STRICH : preis(trade.avg_exit, trade.digits)}
      </td>
      <td
        style={{
          padding: '9px 10px',
          textAlign: 'right',
          color: o.cssColor,
          fontWeight: 700,
        }}
      >
        {geld(trade.net_pnl)}
      </td>
      <td
        style={{
          padding: '9px 10px',
          textAlign: 'right',
          color: trade.r_multiple === null ? 'var(--td-neutral)' : o.cssColor,
        }}
        title={trade.r_multiple === null ? 'kein Stop erfasst' : undefined}
      >
        {rMultiple(trade.r_multiple)}
      </td>
    </tr>
  );
}

function Karte({ trade }: { trade: Trade }) {
  const o = outcome(trade.net_pnl);
  return (
    <Link
      href={`/trades/${trade.id}`}
      className={o.ruleClass}
      style={{
        display: 'block',
        background: 'var(--td-surface)',
        padding: '10px 12px 12px',
        minHeight: 'var(--td-tap)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 10,
        }}
      >
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontWeight: 700, fontSize: 15 }}>{trade.symbol}</span>
          <DirectionPill direction={trade.direction} />
        </div>
        <span
          className="td-display"
          style={{ fontSize: 20, color: o.cssColor }}
        >
          {geld(trade.net_pnl)}
        </span>
      </div>

      <div
        style={{
          display: 'flex',
          gap: 12,
          flexWrap: 'wrap',
          fontSize: 11,
          color: 'var(--td-neutral)',
          marginTop: 4,
        }}
      >
        <span>
          {tagKurz(trade.opened_at ?? '')} {uhrzeit(trade.opened_at)}
        </span>
        <span>{lot(trade.volume)} Lot</span>
        <span>{dauer(trade.duration_seconds)}</span>
        <span
          title={trade.r_multiple === null ? 'kein Stop erfasst' : undefined}
          style={{
            color: trade.r_multiple === null ? 'var(--td-neutral)' : o.cssColor,
          }}
        >
          {rMultiple(trade.r_multiple)}
        </span>
      </div>

      {trade.tags.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
          {trade.tags.map((t) => (
            <TagChip key={t.id} tag={t} />
          ))}
        </div>
      )}
    </Link>
  );
}

export function TradeList({ trades }: { trades: Trade[] }) {
  return (
    <>
      {/* Breit: Tabelle */}
      <div className="td-tabelle">
        <table>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--td-divider)' }}>
              {[
                ['Datum', 'left'],
                ['Symbol', 'left'],
                ['Seite', 'left'],
                ['Lot', 'right'],
                ['Einstieg', 'right'],
                ['Ausstieg', 'right'],
                ['Netto', 'right'],
                ['R', 'right'],
              ].map(([label, align]) => (
                <th
                  key={label}
                  className="td-label"
                  style={{
                    padding: '6px 10px',
                    textAlign: align as 'left' | 'right',
                  }}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <Zeile key={t.id} trade={t} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Schmal: Karten */}
      <div className="td-karten">
        {trades.map((t) => (
          <Karte key={t.id} trade={t} />
        ))}
      </div>
    </>
  );
}
