'use client';

/**
 * Kalender — Muster erkennen, ohne eine Zahl zu lesen.
 */

import { useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { FilterBar, PageHead } from '../../components/Shell';
import { CalendarGrid } from '../../components/CalendarGrid';
import { EmptyState } from '../../components/primitives';
import { api } from '../../lib/api';
import { monatsname } from '../../lib/format';

export default function KalenderSeite() {
  const { accountId } = useApp();
  const heute = new Date();
  const [gewaehlt, setGewaehlt] = useState<{ jahr: number; monat: number } | null>(null);

  // Auf welchen Monat wird geblättert, wenn noch nichts gewählt ist?
  // Nicht stur der laufende: Wer am 1. eines Monats hereinschaut, sähe
  // sonst ein leeres Raster und müsste erst zurückblättern, um seine
  // Historie zu finden. Also der jüngste Monat, in dem gehandelt wurde.
  const juengster = useDaten(
    () => api.trades({ account_id: accountId, limit: 1 }),
    [accountId],
  );

  const letzterTrade = juengster.daten?.trades[0]?.closed_at
    ?? juengster.daten?.trades[0]?.opened_at
    ?? null;
  const vorgabe = letzterTrade
    ? { jahr: Number(letzterTrade.slice(0, 4)), monat: Number(letzterTrade.slice(5, 7)) }
    : { jahr: heute.getFullYear(), monat: heute.getMonth() + 1 };

  const { jahr, monat } = gewaehlt ?? vorgabe;

  const monatsdaten = useDaten(
    () => api.calendar(jahr, monat, accountId),
    [jahr, monat, accountId],
  );
  const symbole = useDaten(() => api.symbols(accountId), [accountId]);

  const blaettern = (schritt: number) => {
    const m = monat + schritt;
    if (m < 1) setGewaehlt({ jahr: jahr - 1, monat: 12 });
    else if (m > 12) setGewaehlt({ jahr: jahr + 1, monat: 1 });
    else setGewaehlt({ jahr, monat: m });
  };

  return (
    <>
      <PageHead
        title="Kalender"
        sub="Farbe zeigt die Richtung, Zahl die Höhe, Kleinschrift die Anzahl"
        right={
          <div style={{ display: 'flex', gap: 2 }}>
            <button
              onClick={() => blaettern(-1)}
              aria-label="Vorheriger Monat"
              style={{ background: 'var(--td-surface)', padding: '0 14px' }}
            >
              ←
            </button>
            <span
              style={{
                background: 'var(--td-surface)',
                padding: '0 14px',
                minHeight: 'var(--td-tap)',
                display: 'flex',
                alignItems: 'center',
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              {monatsname(monat)} {jahr}
            </span>
            <button
              onClick={() => blaettern(1)}
              aria-label="Nächster Monat"
              style={{ background: 'var(--td-surface)', padding: '0 14px' }}
            >
              →
            </button>
          </div>
        }
      />
      <FilterBar symbole={symbole.daten ?? []} />

      <div style={{ marginTop: 16 }}>
        {monatsdaten.fehler ? (
          <EmptyState cause="sync" detail={monatsdaten.fehler} />
        ) : monatsdaten.laedt || !monatsdaten.daten ? (
          <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
        ) : monatsdaten.daten.trading_days === 0 ? (
          <EmptyState
            cause="keine-daten"
            detail={`In ${monatsname(monat)} ${jahr} wurde nicht gehandelt.`}
          />
        ) : (
          <>
            {/* Breit: Raster mit Wochenspalte */}
            <div className="nur-breit">
              <CalendarGrid data={monatsdaten.daten} />
            </div>
            <div className="nur-tablet">
              <CalendarGrid data={monatsdaten.daten} />
            </div>
            {/* Schmal: Raster bleibt Raster, Wochensummen darunter */}
            <div className="nur-schmal">
              <CalendarGrid data={monatsdaten.daten} kompakt />
            </div>
          </>
        )}
      </div>
    </>
  );
}
