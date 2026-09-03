'use client';

/**
 * Der Kalender.
 *
 * Der Wert dieser Ansicht ist nicht, dass man Tage nachschlagen kann —
 * das kann die Trade-Liste auch. Ihr Wert ist, dass man den Monat als
 * *Muster* sieht: drei rote Montage hintereinander, die zweite
 * Monatshälfte durchgehend besser.
 *
 * Deshalb bleibt das Raster auch auf dem Telefon ein Raster. Bei sieben
 * Spalten auf 390 px bleiben rund 50 px pro Zelle — genug für Farbe und
 * Zahl, zu wenig für die Trade-Anzahl. Die erscheint dort beim Antippen,
 * nicht beim Überfahren: Auf dem Telefon gibt es keinen Mauszeiger, und
 * eine Information, die nur im Hover steckt, wäre dort unerreichbar.
 */

import { useState } from 'react';
import type { CalendarDay, CalendarMonth } from '../lib/api';
import { outcome } from '../lib/outcome';
import {
  STRICH,
  geld,
  geldKompakt,
  monatsname,
  prozent,
  wochentag,
} from '../lib/format';

function Zelle({
  tag,
  ausgewaehlt,
  onSelect,
  kompakt,
}: {
  tag: CalendarDay | null;
  ausgewaehlt: boolean;
  onSelect: (d: CalendarDay) => void;
  kompakt: boolean;
}) {
  if (!tag) {
    // Außerhalb des Monats — versenkt, damit das Raster trotzdem steht.
    return <div style={{ background: 'var(--td-sunk)', minHeight: kompakt ? 52 : 74 }} />;
  }

  const gehandelt = tag.trades > 0;
  const o = outcome(gehandelt ? tag.pnl : null, 'kein Handel');
  const nummer = Number(tag.date.slice(8, 10));

  return (
    <button
      onClick={() => onSelect(tag)}
      aria-label={`${tag.date}, ${
        gehandelt ? `${geld(tag.pnl)}, ${tag.trades} Trades` : 'kein Handel'
      }`}
      aria-pressed={ausgewaehlt}
      style={{
        minHeight: kompakt ? 52 : 74,
        padding: kompakt ? '4px 5px' : '6px 8px',
        background: gehandelt ? o.cssTint : 'var(--td-surface)',
        borderTop: gehandelt
          ? `3px solid ${tag.pnl! > 0 ? 'var(--td-pos)' : tag.pnl! < 0 ? 'var(--td-neg-str)' : 'var(--td-neutral)'}`
          : '3px solid transparent',
        outline: ausgewaehlt ? '2px solid var(--td-accent)' : 'none',
        outlineOffset: -2,
        opacity: tag.weekend && !gehandelt ? 0.55 : 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        width: '100%',
      }}
    >
      <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>{nummer}</span>

      {gehandelt ? (
        <>
          <span
            className="td-display"
            style={{
              fontSize: kompakt ? 12 : 15,
              color: o.cssColor,
              lineHeight: 1.1,
            }}
          >
            {geldKompakt(tag.pnl)}
          </span>
          {/* Auf schmalen Breiten weggelassen und per Antippen erreichbar. */}
          {!kompakt && (
            <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>
              {tag.trades} {tag.trades === 1 ? 'Trade' : 'Trades'}
            </span>
          )}
        </>
      ) : (
        <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>
          {tag.weekend ? '' : STRICH}
        </span>
      )}
    </button>
  );
}

export function CalendarGrid({
  data,
  kompakt = false,
  onSelectDay,
}: {
  data: CalendarMonth;
  kompakt?: boolean;
  onSelectDay?: (d: CalendarDay) => void;
}) {
  const [gewaehlt, setGewaehlt] = useState<CalendarDay | null>(null);

  // Vorlauf bis zum ersten Wochentag, damit die Spalten stimmen.
  const ersterTag = data.days[0];
  const vorlauf = ersterTag ? ersterTag.weekday : 0;

  const wochen: (CalendarDay | null)[][] = [];
  let aktuelle: (CalendarDay | null)[] = Array(vorlauf).fill(null);
  for (const tag of data.days) {
    aktuelle.push(tag);
    if (aktuelle.length === 7) {
      wochen.push(aktuelle);
      aktuelle = [];
    }
  }
  if (aktuelle.length) {
    wochen.push([...aktuelle, ...Array(7 - aktuelle.length).fill(null)]);
  }

  const waehle = (t: CalendarDay) => {
    setGewaehlt(t.date === gewaehlt?.date ? null : t);
    onSelectDay?.(t);
  };

  const monatO = outcome(data.month_pnl);

  return (
    <div>
      {/* Monatskopf */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 18,
          alignItems: 'baseline',
          paddingBottom: 12,
        }}
      >
        <div>
          <span className="td-label">
            {monatsname(data.month)} {data.year}
          </span>
          <div
            className="td-display"
            style={{ fontSize: 30, color: monatO.cssColor }}
          >
            {geld(data.month_pnl)}
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
          {data.trading_days} Handelstage
          {data.best_day && (
            <>
              {' · '}bester {data.best_day.date.slice(8, 10)}.{' '}
              <span style={{ color: 'var(--td-pos)' }}>
                {geld(data.best_day.pnl)}
              </span>
            </>
          )}
          {data.worst_day && (
            <>
              {' · '}schlechtester {data.worst_day.date.slice(8, 10)}.{' '}
              <span style={{ color: 'var(--td-neg)' }}>
                {geld(data.worst_day.pnl)}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Spaltenköpfe */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, 1fr)',
          gap: 2,
          paddingBottom: 4,
        }}
      >
        {[0, 1, 2, 3, 4, 5, 6].map((d) => (
          <span key={d} className="td-label" style={{ fontSize: 9 }}>
            {wochentag(d, true)}
          </span>
        ))}
      </div>

      {/* Das Raster. 2px Fuge — die Zellen stoßen aneinander, sie
          schwimmen nicht in Weißraum. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {wochen.map((woche, i) => {
          const kw = woche.find((t) => t)?.iso_week;
          const summe = data.weeks.find((w) => w.iso_week === kw);
          return (
            <div key={i} style={{ display: 'flex', gap: 2 }}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(7, 1fr)',
                  gap: 2,
                  flex: 1,
                }}
              >
                {woche.map((tag, j) => (
                  <Zelle
                    key={j}
                    tag={tag}
                    kompakt={kompakt}
                    ausgewaehlt={!!tag && tag.date === gewaehlt?.date}
                    onSelect={waehle}
                  />
                ))}
              </div>

              {/* Wochensumme, optisch abgesetzt. */}
              {!kompakt && (
                <div
                  style={{
                    width: 96,
                    background: 'var(--td-sunk)',
                    padding: '6px 8px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                  }}
                >
                  <span className="td-label" style={{ fontSize: 9 }}>
                    KW {kw ?? ''}
                  </span>
                  {summe && summe.trades > 0 ? (
                    <>
                      <span
                        className="td-display"
                        style={{
                          fontSize: 13,
                          color: outcome(summe.pnl).cssColor,
                        }}
                      >
                        {geld(summe.pnl)}
                      </span>
                      <span style={{ fontSize: 9, color: 'var(--td-neutral)' }}>
                        {summe.trades} Trades · {summe.days} Tage
                      </span>
                    </>
                  ) : (
                    <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
                      {STRICH}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Auf schmalen Breiten liefert das Antippen nach, was in die Zelle
          nicht passt. */}
      {gewaehlt && (
        <div
          style={{
            marginTop: 10,
            padding: '10px 12px',
            background: 'var(--td-surface)',
            borderTop: `3px solid ${outcome(gewaehlt.pnl).cssColor}`,
          }}
        >
          <span className="td-label">{gewaehlt.date}</span>
          <div style={{ display: 'flex', gap: 16, marginTop: 4, flexWrap: 'wrap' }}>
            <span
              className="td-display"
              style={{ fontSize: 20, color: outcome(gewaehlt.pnl).cssColor }}
            >
              {gewaehlt.trades ? geld(gewaehlt.pnl) : STRICH}
            </span>
            <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
              {gewaehlt.trades
                ? `${gewaehlt.trades} Trades · ${gewaehlt.wins} gewonnen · Quote ${prozent(
                    gewaehlt.win_rate,
                  )}`
                : 'kein Handel an diesem Tag'}
            </span>
          </div>
        </div>
      )}

      {/* Wochensummen auf schmalen Breiten, wo die Spalte nicht passt. */}
      {kompakt && (
        <div style={{ marginTop: 10 }}>
          <span className="td-label">Wochen</span>
          {data.weeks
            .filter((w) => w.trades > 0)
            .map((w) => (
              <div
                key={w.iso_week}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  minHeight: 30,
                  alignItems: 'center',
                  borderTop: '1px solid var(--td-line)',
                }}
              >
                <span style={{ fontSize: 11 }}>
                  KW {w.iso_week}
                  <span style={{ color: 'var(--td-neutral)' }}>
                    {' '}
                    · {w.trades} Trades
                  </span>
                </span>
                <span
                  style={{ color: outcome(w.pnl).cssColor, fontWeight: 600 }}
                >
                  {geld(w.pnl)}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
