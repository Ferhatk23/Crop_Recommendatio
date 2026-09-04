'use client';

/**
 * Tagesjournal — einen Handelstag als Ganzes nachbereiten.
 *
 * Der Intraday-Verlauf ist das Kernstück: Er beantwortet, ob ein guter
 * Tag ein guter Tag war oder eine gerettete Katastrophe.
 */

import { useEffect, useMemo, useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { PageHead } from '../../components/Shell';
import { NotizFeld, StimmungsWahl } from '../../components/Schreiben';
import { TradeList } from '../../components/TradeList';
import { EmptyState, KpiTile } from '../../components/primitives';
import { api } from '../../lib/api';
import { outcome } from '../../lib/outcome';
import { faktor, geld, geldKompakt, prozent, uhrzeit, zahl } from '../../lib/format';

function IntradayVerlauf({
  punkte,
}: {
  punkte: { t: string; kumuliert: number }[];
}) {
  if (punkte.length < 2) return null;
  const B = 100, H = 34, pad = 3;
  const werte = punkte.map((p) => p.kumuliert);
  const max = Math.max(...werte, 0), min = Math.min(...werte, 0);
  const spanne = max - min || 1;
  const x = (i: number) => (i / (punkte.length - 1)) * B;
  const y = (v: number) => H - pad - ((v - min) / spanne) * (H - pad * 2);
  const o = outcome(punkte[punkte.length - 1].kumuliert);

  return (
    <svg
      viewBox={`0 0 ${B} ${H}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height: 130, display: 'block' }}
      role="img"
      aria-label="Verlauf des realisierten Ergebnisses über den Tag"
    >
      <line
        x1="0" x2={B} y1={y(0)} y2={y(0)}
        stroke="var(--td-neutral)" strokeWidth="0.2"
        strokeDasharray="1 1" vectorEffect="non-scaling-stroke"
      />
      <polyline
        points={punkte.map((p, i) => `${x(i)},${y(p.kumuliert)}`).join(' ')}
        fill="none" stroke={o.cssColor} strokeWidth="2"
        vectorEffect="non-scaling-stroke" strokeLinejoin="round"
      />
      {punkte.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.kumuliert)} r="1.2" fill={o.cssColor} />
      ))}
    </svg>
  );
}

export default function JournalSeite() {
  const { accountId, account } = useApp();
  const [tag, setTag] = useState<string | null>(null);

  const alle = useDaten(
    () => api.trades({ account_id: accountId, limit: 1000 }),
    [accountId],
  );

  const tage = useMemo(() => {
    const gruppen = new Map<string, typeof alle.daten extends null ? never : NonNullable<typeof alle.daten>['trades']>();
    for (const t of alle.daten?.trades ?? []) {
      if (!t.closed_at) continue;
      const d = t.closed_at.slice(0, 10);
      if (!gruppen.has(d)) gruppen.set(d, []);
      gruppen.get(d)!.push(t);
    }
    return [...gruppen.entries()]
      .map(([datum, trades]) => ({
        datum,
        trades: [...trades].sort((a, b) => (a.closed_at! < b.closed_at! ? -1 : 1)),
        netto: trades.reduce((s, t) => s + t.net_pnl, 0),
      }))
      .sort((a, b) => (a.datum < b.datum ? 1 : -1));
  }, [alle.daten]);

  const gewaehlt = tage.find((t) => t.datum === tag) ?? tage[0] ?? null;

  const verlauf = useMemo(() => {
    if (!gewaehlt) return [];
    let summe = 0;
    return gewaehlt.trades.map((t) => {
      summe += t.net_pnl;
      return { t: t.closed_at!, kumuliert: summe };
    });
  }, [gewaehlt]);

  if (alle.fehler) {
    return (<><PageHead title="Tagesjournal" /><EmptyState cause="sync" detail={alle.fehler} /></>);
  }
  if (alle.laedt) {
    return (<><PageHead title="Tagesjournal" /><div style={{ color: 'var(--td-neutral)' }}>lädt …</div></>);
  }
  if (!gewaehlt) {
    return (<><PageHead title="Tagesjournal" /><EmptyState cause="keine-daten" /></>);
  }

  const gewinner = gewaehlt.trades.filter((t) => t.net_pnl > 0);
  const verlierer = gewaehlt.trades.filter((t) => t.net_pnl < 0);
  const brutto = gewinner.reduce((s, t) => s + t.net_pnl, 0);
  const verlust = -verlierer.reduce((s, t) => s + t.net_pnl, 0);
  const entschieden = gewinner.length + verlierer.length;

  return (
    <>
      <PageHead
        title="Tagesjournal"
        sub={`${account?.label ?? ''} · ${gewaehlt.datum}`}
        right={
          <select
            aria-label="Handelstag"
            value={gewaehlt.datum}
            onChange={(e) => setTag(e.target.value)}
            style={{ minWidth: 170 }}
          >
            {tage.map((t) => (
              <option key={t.datum} value={t.datum}>
                {t.datum} · {geldKompakt(t.netto, '€')}
              </option>
            ))}
          </select>
        }
      />

      <div className="td-grid td-grid-4" style={{ marginTop: 12 }}>
        <KpiTile
          label="Netto am Tag" value={geld(gewaehlt.netto)}
          outcomeValue={gewaehlt.netto} period={gewaehlt.datum} large
        />
        <KpiTile
          label="Trades" value={zahl(gewaehlt.trades.length)}
          outcomeValue={null}
          compare={`${gewinner.length} G · ${verlierer.length} V`} large
        />
        <KpiTile
          label="Trefferquote"
          value={entschieden ? prozent(gewinner.length / entschieden) : '—'}
          outcomeValue={null}
          reason={entschieden ? undefined : 'nur Break-even-Trades'} large
        />
        <KpiTile
          label="Profit Factor"
          value={verlust > 0 ? faktor(brutto / verlust) : '—'}
          outcomeValue={null}
          reason={verlust > 0 ? undefined : 'kein Verlust an diesem Tag'} large
        />
      </div>

      <section className="td-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span className="td-label">Verlauf über den Tag</span>
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            {uhrzeit(gewaehlt.trades[0]?.closed_at)} –{' '}
            {uhrzeit(gewaehlt.trades[gewaehlt.trades.length - 1]?.closed_at)}
          </span>
        </div>
        <div className="td-card" style={{ marginTop: 6 }}>
          <IntradayVerlauf punkte={verlauf} />
          <p style={{ fontSize: 11, color: 'var(--td-neutral)', margin: '6px 0 0' }}>
            Jeder Punkt ist ein geschlossener Trade. Der Verlauf zeigt, ob ein
            guter Tag ein guter Tag war — oder eine gerettete Katastrophe.
          </p>
        </div>
      </section>

      <section className="td-section">
        <span className="td-label">Trades des Tages</span>
        <div style={{ marginTop: 6 }}>
          <TradeList trades={gewaehlt.trades} />
        </div>
      </section>

      <section className="td-section">
        <Tagesnotiz datum={gewaehlt.datum} accountId={accountId} />
      </section>
    </>
  );
}

/**
 * Die Notiz zu einem Handelstag.
 *
 * Eigene Komponente, damit der Wechsel des Tages sie neu lädt — und
 * damit die Notiz des einen Tages niemals im Feld des nächsten steht.
 */
function Tagesnotiz({
  datum,
  accountId,
}: {
  datum: string;
  accountId: number | null;
}) {
  const eintrag = useDaten(
    () => (accountId ? api.journal(datum, accountId) : Promise.resolve(null)),
    [datum, accountId],
  );
  const [stimmung, setStimmung] = useState<number | null>(null);
  const [stimmungsFehler, setStimmungsFehler] = useState<string | null>(null);

  useEffect(() => {
    setStimmung(eintrag.daten?.mood ?? null);
    setStimmungsFehler(null);
  }, [eintrag.daten]);

  if (!accountId) return null;
  if (eintrag.fehler) {
    return (
      <>
        <span className="td-label">Tagesnotiz</span>
        <div className="td-card" style={{ marginTop: 6, color: 'var(--td-neg)' }}>
          ⚠ {eintrag.fehler}
        </div>
      </>
    );
  }
  if (eintrag.laedt || !eintrag.daten) {
    return (
      <>
        <span className="td-label">Tagesnotiz</span>
        <div style={{ marginTop: 6, color: 'var(--td-neutral)' }}>lädt …</div>
      </>
    );
  }

  const daten = eintrag.daten;

  const stimmungSetzen = async (wert: number | null) => {
    const vorher = stimmung;
    setStimmung(wert);
    setStimmungsFehler(null);
    try {
      await api.journal_schreiben(datum, accountId, {
        body: daten.body,
        mood: wert,
      });
    } catch (e) {
      // Zurück auf den letzten bestätigten Stand: Eine Anzeige, die
      // etwas anderes zeigt als der Server hat, ist schlimmer als gar keine.
      setStimmung(vorher);
      setStimmungsFehler(
        e instanceof Error ? e.message : 'Speichern fehlgeschlagen',
      );
    }
  };

  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          columnGap: 12,
          rowGap: 6,
          marginBottom: 8,
        }}
      >
        <span className="td-label">Verfassung an diesem Tag</span>
        <StimmungsWahl wert={stimmung} onWahl={(w) => void stimmungSetzen(w)} />
      </div>
      {stimmungsFehler && (
        <div
          role="status"
          style={{
            fontSize: 11,
            color: 'var(--td-neg)',
            fontWeight: 600,
            marginBottom: 8,
          }}
        >
          ⚠ {stimmungsFehler}
        </div>
      )}

      <NotizFeld
        label={`Tagesnotiz · ${datum}`}
        wert={daten.body}
        zeilen={8}
        platzhalter="Wie war der Tag? Was lief nach Plan, was nicht? Was nimmst du morgen mit?"
        onSpeichern={(text) =>
          api.journal_schreiben(datum, accountId, { body: text, mood: stimmung })
        }
      />
    </>
  );
}
