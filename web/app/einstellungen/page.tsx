'use client';

/**
 * Konten anlegen und ihre Grenzwerte pflegen.
 *
 * Diese Seite ist der Grund, warum die App nach einer frischen
 * Installation überhaupt benutzbar ist: Vorher gab es einen Nutzer und
 * ein leeres Schema, und kein Weg führte zum eigenen Handelskonto ausser
 * von Hand per SQL.
 *
 * Die Grenzwerte sind der eigentliche Inhalt. Sie sind nicht Beiwerk,
 * sondern der Grund, warum es die Regel-Puffer auf dem Dashboard gibt.
 * Ein falsch eingetragenes Limit zeigt einen Puffer, den es nicht gibt --
 * und das ist schlimmer als gar keiner, weil man sich darauf verlässt.
 * Deshalb steht an jedem Feld, was es bedeutet, und die Konsistenzregel
 * sagt ausdrücklich, dass 40 % als 0,4 einzutragen sind.
 */

import { useState } from 'react';
import { useApp, useDaten } from '../../components/AppState';
import { PageHead } from '../../components/Shell';
import { EmptyState } from '../../components/primitives';
import {
  PHASEN,
  STATUS,
  api,
  type Account,
  type KontoFelder,
} from '../../lib/api';
import { betrag, prozent, zahl } from '../../lib/format';

/* ------------------------------------------------------------------ */

const feldStil: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  background: 'var(--td-bg)',
  border: '1px solid var(--td-line)',
  color: 'var(--td-text)',
  font: 'inherit',
  fontSize: 13,
};

function Feld({
  label,
  hinweis,
  kind,
}: {
  label: string;
  hinweis?: string;
  kind: React.ReactNode;
}) {
  return (
    <label style={{ display: 'block' }}>
      <span className="td-label">{label}</span>
      {kind}
      {hinweis && (
        <span
          style={{
            display: 'block',
            fontSize: 10,
            color: 'var(--td-neutral)',
            marginTop: 3,
            lineHeight: 1.45,
          }}
        >
          {hinweis}
        </span>
      )}
    </label>
  );
}

/** Leerer Text wird `null`, nicht 0 — sonst wäre "kein Limit" ein Limit von 0. */
function alsZahl(text: string): number | null {
  const sauber = text.trim().replace(',', '.');
  if (sauber === '') return null;
  const wert = Number(sauber);
  return Number.isFinite(wert) ? wert : null;
}

const LEER: Record<string, string> = {
  label: '',
  broker: '',
  server: '',
  login: '',
  currency: 'EUR',
  phase: 'challenge',
  status: 'aktiv',
  starting_balance: '',
  daily_loss_limit: '',
  max_loss_limit: '',
  consistency_limit: '',
  profit_target: '',
};

function ausKonto(k: Account): Record<string, string> {
  const t = (v: number | string | null | undefined) =>
    v === null || v === undefined ? '' : String(v);
  return {
    label: k.label,
    broker: t(k.broker),
    server: t(k.server),
    login: t(k.login),
    currency: k.currency,
    phase: k.phase,
    status: k.status,
    starting_balance: t(k.starting_balance),
    daily_loss_limit: t(k.limits.daily_loss),
    max_loss_limit: t(k.limits.max_loss),
    consistency_limit: t(k.limits.consistency),
    profit_target: t(k.limits.profit_target),
  };
}

/* ------------------------------------------------------------------ */
/* Formular                                                            */
/* ------------------------------------------------------------------ */

function KontoFormular({
  start,
  konto,
  onFertig,
  onAbbrechen,
}: {
  start: Record<string, string>;
  konto?: Account;
  onFertig: () => void;
  onAbbrechen?: () => void;
}) {
  const [werte, setWerte] = useState(start);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const setze = (feld: string) => (e: { target: { value: string } }) =>
    setWerte((alt) => ({ ...alt, [feld]: e.target.value }));

  const absenden = async (e: React.FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setLaeuft(true);
    setFehler(null);

    const felder: KontoFelder = {
      label: werte.label.trim(),
      broker: werte.broker.trim() || null,
      server: werte.server.trim() || null,
      login: werte.login.trim() || null,
      currency: werte.currency.trim() || 'EUR',
      phase: werte.phase,
      status: werte.status,
      starting_balance: alsZahl(werte.starting_balance) ?? 0,
      daily_loss_limit: alsZahl(werte.daily_loss_limit),
      max_loss_limit: alsZahl(werte.max_loss_limit),
      consistency_limit: alsZahl(werte.consistency_limit),
      profit_target: alsZahl(werte.profit_target),
    };

    try {
      if (konto) await api.konto_aendern(konto.id, felder);
      else await api.konto_anlegen(felder);
      onFertig();
    } catch (fehlschlag) {
      setFehler(
        fehlschlag instanceof Error ? fehlschlag.message : 'Speichern fehlgeschlagen',
      );
      setLaeuft(false);
    }
  };

  const startkapitalGeaendert =
    konto !== undefined &&
    konto.deal_count > 0 &&
    alsZahl(werte.starting_balance) !== konto.starting_balance;

  return (
    <form onSubmit={absenden} className="td-card" style={{ marginTop: 8 }}>
      <div className="td-grid td-grid-2" style={{ gap: 12, background: 'none' }}>
        <Feld
          label="Bezeichnung"
          hinweis="Wie es in der Kontoauswahl steht"
          kind={
            <input
              required
              value={werte.label}
              onChange={setze('label')}
              placeholder="Alpha 100k · Funded"
              style={feldStil}
            />
          }
        />
        <Feld
          label="Broker"
          kind={
            <input
              value={werte.broker}
              onChange={setze('broker')}
              placeholder="Alpha Capital"
              style={feldStil}
            />
          }
        />
        <Feld
          label="Server"
          hinweis="Wie im MT5-Terminal — für den Sammler"
          kind={
            <input
              value={werte.server}
              onChange={setze('server')}
              placeholder="AlphaCapital-Live02"
              style={feldStil}
            />
          }
        />
        <Feld
          label="Kontonummer"
          hinweis="Nur zur Wiedererkennung. Das Passwort steht hier nie."
          kind={
            <input value={werte.login} onChange={setze('login')} style={feldStil} />
          }
        />
        <Feld
          label="Phase"
          kind={
            <select value={werte.phase} onChange={setze('phase')} style={feldStil}>
              {PHASEN.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          }
        />
        <Feld
          label="Status"
          hinweis="Ein verlorenes Konto gehört auf „verloren“, nicht gelöscht"
          kind={
            <select value={werte.status} onChange={setze('status')} style={feldStil}>
              {STATUS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          }
        />
        <Feld
          label="Startkapital"
          hinweis="Der Nullpunkt der Equity-Kurve"
          kind={
            <input
              inputMode="decimal"
              value={werte.starting_balance}
              onChange={setze('starting_balance')}
              placeholder="100000"
              style={feldStil}
            />
          }
        />
        <Feld
          label="Währung"
          kind={
            <input
              value={werte.currency}
              onChange={setze('currency')}
              maxLength={8}
              style={feldStil}
            />
          }
        />
      </div>

      {startkapitalGeaendert && (
        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            borderLeft: '2px solid var(--td-line)',
            paddingLeft: 10,
            margin: '14px 0 0',
            lineHeight: 1.6,
          }}
        >
          Am Konto hängen {zahl(konto!.deal_count)} Ausführungen. Ein anderes
          Startkapital verschiebt die ganze Equity-Kurve und damit den
          mitlaufenden Maximalverlust — die einzelnen Trades bleiben unberührt.
        </p>
      )}

      {/* --- Die Grenzwerte ------------------------------------------- */}

      <div className="td-section" style={{ marginTop: 18 }}>
        <span className="td-label">Grenzwerte der Prop-Firma</span>
        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            margin: '4px 0 12px',
            lineHeight: 1.6,
          }}
        >
          Daraus rechnen sich die Puffer auf dem Dashboard. Leer lassen, was es
          bei diesem Konto nicht gibt — ein Privatkonto hat keine dieser
          Grenzen, und dann zeigt die App keinen Puffer statt eines erfundenen.
        </p>

        <div className="td-grid td-grid-2" style={{ gap: 12, background: 'none' }}>
          <Feld
            label="Tagesverlust"
            hinweis="Höchstverlust an einem Handelstag"
            kind={
              <input
                inputMode="decimal"
                value={werte.daily_loss_limit}
                onChange={setze('daily_loss_limit')}
                placeholder="5000"
                style={feldStil}
              />
            }
          />
          <Feld
            label="Gesamtverlust"
            hinweis="Mitlaufend vom höchsten Kontostand aus"
            kind={
              <input
                inputMode="decimal"
                value={werte.max_loss_limit}
                onChange={setze('max_loss_limit')}
                placeholder="10000"
                style={feldStil}
              />
            }
          />
          <Feld
            label="Konsistenzregel"
            hinweis="Als Anteil, nicht als Prozent: 40 % werden 0,4 eingetragen"
            kind={
              <input
                inputMode="decimal"
                value={werte.consistency_limit}
                onChange={setze('consistency_limit')}
                placeholder="0,4"
                style={feldStil}
              />
            }
          />
          <Feld
            label="Gewinnziel"
            hinweis="Für Challenge und Verifikation"
            kind={
              <input
                inputMode="decimal"
                value={werte.profit_target}
                onChange={setze('profit_target')}
                placeholder="10000"
                style={feldStil}
              />
            }
          />
        </div>
      </div>

      {fehler && (
        <div
          role="alert"
          style={{
            marginTop: 14,
            padding: '8px 10px',
            fontSize: 12,
            color: 'var(--td-neg)',
            fontWeight: 600,
            borderLeft: '3px solid var(--td-neg-str)',
            background: 'var(--td-neg-t)',
          }}
        >
          ⚠ {fehler}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
        <button
          type="submit"
          disabled={laeuft}
          style={{
            padding: '9px 16px',
            background: laeuft ? 'transparent' : 'var(--td-accent)',
            color: laeuft ? 'var(--td-neutral)' : 'var(--td-on-accent)',
            border: '1px solid var(--td-line)',
            fontWeight: 600,
            fontSize: 12,
          }}
        >
          {laeuft ? 'speichert …' : konto ? 'Speichern' : 'Konto anlegen'}
        </button>
        {onAbbrechen && (
          <button
            type="button"
            onClick={onAbbrechen}
            style={{
              padding: '9px 14px',
              background: 'transparent',
              border: '1px solid var(--td-line)',
              color: 'var(--td-neutral)',
              fontSize: 12,
            }}
          >
            Abbrechen
          </button>
        )}
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ */
/* Ein Konto in der Liste                                              */
/* ------------------------------------------------------------------ */

function KontoZeile({
  konto,
  onGeaendert,
}: {
  konto: Account;
  onGeaendert: () => void;
}) {
  const [offen, setOffen] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const loeschen = async () => {
    setFehler(null);
    try {
      await api.konto_loeschen(konto.id);
      onGeaendert();
    } catch (e) {
      setFehler(e instanceof Error ? e.message : 'Löschen fehlgeschlagen');
    }
  };

  const grenze = (wert: number | null, alsAnteil = false) =>
    wert === null ? '—' : alsAnteil ? prozent(wert, 0) : betrag(wert);

  return (
    <div style={{ borderTop: '1px solid var(--td-line)', padding: '12px 0' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 12,
          rowGap: 4,
        }}
      >
        <div>
          <span style={{ fontWeight: 600 }}>{konto.label}</span>
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            {' · '}
            {konto.phase}
            {konto.status !== 'aktiv' ? ` · ${konto.status}` : ''}
            {konto.deal_count > 0
              ? ` · ${zahl(konto.deal_count)} Ausführungen`
              : ' · noch keine Daten'}
          </span>
        </div>
        <button
          onClick={() => setOffen((a) => !a)}
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            textDecoration: 'underline',
            minHeight: 32,
          }}
        >
          {offen ? 'schliessen' : 'bearbeiten'}
        </button>
      </div>

      <div
        style={{
          fontSize: 11,
          color: 'var(--td-neutral)',
          marginTop: 4,
          display: 'flex',
          flexWrap: 'wrap',
          columnGap: 14,
        }}
      >
        <span>Start {grenze(konto.starting_balance)}</span>
        <span>Tag {grenze(konto.limits.daily_loss)}</span>
        <span>Gesamt {grenze(konto.limits.max_loss)}</span>
        <span>Konsistenz {grenze(konto.limits.consistency, true)}</span>
      </div>

      {fehler && (
        <div
          role="alert"
          style={{
            marginTop: 8,
            fontSize: 11,
            color: 'var(--td-neg)',
            fontWeight: 600,
            lineHeight: 1.5,
          }}
        >
          ⚠ {fehler}
        </div>
      )}

      {offen && (
        <>
          <KontoFormular
            start={ausKonto(konto)}
            konto={konto}
            onFertig={() => {
              setOffen(false);
              onGeaendert();
            }}
            onAbbrechen={() => setOffen(false)}
          />
          {konto.deal_count === 0 && (
            <button
              onClick={() => void loeschen()}
              style={{
                marginTop: 10,
                fontSize: 11,
                color: 'var(--td-neg)',
                textDecoration: 'underline',
                minHeight: 32,
              }}
            >
              Dieses leere Konto löschen
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function EinstellungenSeite() {
  const { neuLaden, nutzer } = useApp();
  const [runde, setRunde] = useState(0);
  const [neuOffen, setNeuOffen] = useState(false);

  const konten = useDaten(() => api.accounts(), [runde]);

  const aktualisieren = () => {
    setRunde((r) => r + 1);
    // Auch der globale Zustand muss nachziehen -- sonst zeigt die
    // Kontoauswahl in der Seitenleiste noch den alten Stand.
    neuLaden();
  };

  if (konten.fehler) {
    return (
      <>
        <PageHead title="Einstellungen" />
        <EmptyState cause="sync" detail={konten.fehler} />
      </>
    );
  }

  const liste = konten.daten ?? [];

  return (
    <>
      <PageHead title="Einstellungen" sub={nutzer?.email ?? undefined} />

      <section className="td-section" style={{ marginTop: 4 }}>
        <span className="td-label">Konten</span>

        {konten.laedt ? (
          <div style={{ color: 'var(--td-neutral)', marginTop: 8 }}>lädt …</div>
        ) : liste.length === 0 ? (
          <p
            style={{
              fontSize: 12,
              color: 'var(--td-neutral)',
              lineHeight: 1.6,
              margin: '8px 0 0',
            }}
          >
            Noch kein Konto. Leg dein Handelskonto an — die Grenzwerte deiner
            Prop-Firma stehen in der Kontoeröffnungs-Mail.
          </p>
        ) : (
          <div style={{ marginTop: 6 }}>
            {liste.map((k) => (
              <KontoZeile key={k.id} konto={k} onGeaendert={aktualisieren} />
            ))}
          </div>
        )}

        {neuOffen ? (
          <div style={{ marginTop: 14 }}>
            <span className="td-label">Neues Konto</span>
            <KontoFormular
              start={LEER}
              onFertig={() => {
                setNeuOffen(false);
                aktualisieren();
              }}
              onAbbrechen={() => setNeuOffen(false)}
            />
          </div>
        ) : (
          <button
            onClick={() => setNeuOffen(true)}
            style={{
              marginTop: 14,
              padding: '9px 16px',
              background: 'var(--td-accent)',
              color: 'var(--td-on-accent)',
              border: '1px solid var(--td-line)',
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Konto hinzufügen
          </button>
        )}
      </section>

      <section className="td-section">
        <span className="td-label">Der Sammler</span>
        <p
          style={{
            fontSize: 12,
            color: 'var(--td-neutral)',
            lineHeight: 1.7,
            margin: '6px 0 0',
          }}
        >
          Damit Trades automatisch einlaufen, braucht der Sammler eine
          Zugangsmarke. Die wird am Rechner angelegt, nicht hier — sie wird
          genau einmal angezeigt und danach nur noch als Hash gespeichert:
          <br />
          <code style={{ fontSize: 11 }}>
            python scripts/marke.py anlegen &lt;konto-nummer&gt;
          </code>
          <br />
          Die Marke darf nur einliefern, nicht lesen. Einrichtung in{' '}
          <code style={{ fontSize: 11 }}>collector/README.md</code>.
        </p>
      </section>
    </>
  );
}
