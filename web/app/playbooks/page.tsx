'use client';

/**
 * Playbooks anlegen und pflegen.
 *
 * Ein Playbook ist die schriftliche Fassung dessen, was man zu handeln
 * behauptet. Bisher liessen sie sich einem Trade zuordnen, aber nirgends
 * schreiben — man hätte sie von Hand per SQL eintragen müssen.
 *
 * Zwei Dinge trägt die Seite ausdrücklich:
 *
 * * **Die Reihenfolge ist der Ablauf.** Eine Regelliste wird von oben nach
 *   unten abgearbeitet, also lässt sie sich hier verschieben und wird nicht
 *   sortiert.
 * * **Regeln behalten ihre Identität.** Beim Speichern geht jede vorhandene
 *   Regel mit ihrer `id` zurück. Ohne das verlöre eine Tippfehlerkorrektur
 *   sämtliche Häkchen, die je an dieser Regel gesetzt wurden — lautlos,
 *   denn die Oberfläche zeigte danach einfach leere Kästchen.
 */

import { useState } from 'react';
import { useDaten } from '../../components/AppState';
import { PageHead } from '../../components/Shell';
import { EmptyState } from '../../components/primitives';
import {
  api,
  type Playbook,
  type Pruefung,
  type RegelEingabe,
} from '../../lib/api';
import { zahl } from '../../lib/format';

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

const knopfStil: React.CSSProperties = {
  padding: '9px 16px',
  background: 'var(--td-accent)',
  color: 'var(--td-on-accent)',
  border: '1px solid var(--td-line)',
  fontWeight: 600,
  fontSize: 12,
};

const nebenStil: React.CSSProperties = {
  padding: '9px 14px',
  background: 'transparent',
  border: '1px solid var(--td-line)',
  color: 'var(--td-neutral)',
  fontSize: 12,
};

function Meldung({ text }: { text: string }) {
  return (
    <div
      role="alert"
      style={{
        marginTop: 12,
        padding: '8px 10px',
        fontSize: 12,
        color: 'var(--td-neg)',
        fontWeight: 600,
        borderLeft: '3px solid var(--td-neg-str)',
        background: 'var(--td-neg-tint)',
        lineHeight: 1.5,
      }}
    >
      ⚠ {text}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Regelzeile                                                          */
/* ------------------------------------------------------------------ */

function RegelZeile({
  regel,
  erste,
  letzte,
  pruefungen,
  onAendern,
  onVerschieben,
  onEntfernen,
}: {
  regel: RegelEingabe;
  erste: boolean;
  letzte: boolean;
  pruefungen: Pruefung[];
  onAendern: (feld: keyof RegelEingabe, wert: string | boolean | null) => void;
  onVerschieben: (richtung: -1 | 1) => void;
  onEntfernen: () => void;
}) {
  const pruefung = pruefungen.find((p) => p.key === regel.auto_check) ?? null;
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'flex-start',
        padding: '8px 0',
        borderTop: '1px solid var(--td-line)',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <button
          type="button"
          onClick={() => onVerschieben(-1)}
          disabled={erste}
          aria-label="nach oben"
          style={{
            width: 26,
            height: 22,
            fontSize: 11,
            color: erste ? 'var(--td-line)' : 'var(--td-neutral)',
            border: '1px solid var(--td-line)',
            background: 'transparent',
          }}
        >
          ▲
        </button>
        <button
          type="button"
          onClick={() => onVerschieben(1)}
          disabled={letzte}
          aria-label="nach unten"
          style={{
            width: 26,
            height: 22,
            fontSize: 11,
            color: letzte ? 'var(--td-line)' : 'var(--td-neutral)',
            border: '1px solid var(--td-line)',
            borderTop: 'none',
            background: 'transparent',
          }}
        >
          ▼
        </button>
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'grid', gap: 6 }}>
        <input
          value={regel.text}
          onChange={(e) => onAendern('text', e.target.value)}
          aria-label="Regel"
          placeholder="Stop hinter der Range gesetzt"
          style={feldStil}
        />
        <div
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <input
            value={regel.group}
            onChange={(e) => onAendern('group', e.target.value)}
            aria-label="Gruppe"
            placeholder="Vorbereitung"
            style={{ ...feldStil, width: 170, fontSize: 11 }}
          />
          {/* Der Unterschied ist nicht kosmetisch: Nur abhakbare Regeln
              zählen in die Regeltreue. Ein Merksatz wie „ruhig bleiben"
              lässt sich am einzelnen Trade nicht mit ja oder nein
              beantworten — in einer Quote wäre er Füllmaterial. */}
          {!regel.auto_check && (
            <label
              style={{
                display: 'flex',
                gap: 6,
                alignItems: 'center',
                fontSize: 11,
                color: 'var(--td-neutral)',
              }}
            >
              <input
                type="checkbox"
                checked={regel.checkable}
                onChange={(e) => onAendern('checkable', e.target.checked)}
              />
              am Trade abhakbar
            </label>
          )}

          {/* Wo eine Prüfung greift, wird gemessen statt gefragt. Das ist
              die verlässlichste Antwort, die diese App geben kann: Wer
              sein Journal abends führt, erinnert sich an den Einstieg
              anders, wenn er das Ergebnis schon kennt. */}
          <select
            aria-label="Prüfung"
            value={regel.auto_check ?? ''}
            onChange={(e) => onAendern('auto_check', e.target.value || null)}
            style={{ ...feldStil, width: 'auto', fontSize: 11 }}
          >
            <option value="">von Hand abhaken</option>
            {pruefungen.map((p) => (
              <option key={p.key} value={p.key}>
                messen: {p.label}
              </option>
            ))}
          </select>

          {pruefung?.einheit && (
            <input
              value={regel.auto_param ?? ''}
              onChange={(e) => onAendern('auto_param', e.target.value)}
              aria-label={pruefung.einheit}
              placeholder={pruefung.beispiel ?? ''}
              style={{ ...feldStil, width: 90, fontSize: 11 }}
            />
          )}
          {pruefung?.einheit && (
            <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
              {pruefung.einheit}
            </span>
          )}
          <button
            type="button"
            onClick={onEntfernen}
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              color: 'var(--td-neg)',
              textDecoration: 'underline',
              minHeight: 32,
            }}
          >
            entfernen
          </button>
        </div>

        {/* Warum eine Prüfung manchmal offen bleibt, gehört an die
            Prüfung -- sonst sucht man den Grund in den Daten. */}
        {pruefung && (
          <p
            style={{
              fontSize: 10,
              color: 'var(--td-neutral)',
              margin: '2px 0 0',
              lineHeight: 1.5,
            }}
          >
            {pruefung.beschreibung}
          </p>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Formular                                                            */
/* ------------------------------------------------------------------ */

function PlaybookFormular({
  buch,
  pruefungen,
  onFertig,
  onAbbrechen,
}: {
  buch?: Playbook;
  pruefungen: Pruefung[];
  onFertig: () => void;
  onAbbrechen: () => void;
}) {
  const [name, setName] = useState(buch?.name ?? '');
  const [text, setText] = useState(buch?.description ?? '');
  // Die vorhandenen `id` gehen mit — daran hängen alle bisherigen Häkchen.
  const [regeln, setRegeln] = useState<RegelEingabe[]>(
    buch?.rules.map((r) => ({
      id: r.id,
      group: r.group,
      text: r.text,
      checkable: r.checkable,
      auto_check: r.auto_check,
      auto_param: r.auto_param,
    })) ?? [{ group: 'Allgemein', text: '', checkable: true }],
  );
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  // Die Rückfrage beim Streichen beantworteter Regeln. Der Server sagt,
  // wie viele Antworten daran hängen; hier steht nur die Zustimmung.
  const [rueckfrage, setRueckfrage] = useState<string | null>(null);

  const setzeRegel = (
    i: number,
    feld: keyof RegelEingabe,
    wert: string | boolean | null,
  ) =>
    setRegeln((alt) =>
      alt.map((r, j) => (i === j ? { ...r, [feld]: wert } : r)),
    );

  const verschiebe = (i: number, richtung: -1 | 1) =>
    setRegeln((alt) => {
      const ziel = i + richtung;
      if (ziel < 0 || ziel >= alt.length) return alt;
      const neu = [...alt];
      [neu[i], neu[ziel]] = [neu[ziel], neu[i]];
      return neu;
    });

  const speichern = async (verwerfen: boolean) => {
    if (laeuft) return;
    setLaeuft(true);
    setFehler(null);

    // Leere Zeilen fallen weg — sie kommen vom „Regel hinzufügen", das
    // man einmal zu oft gedrückt hat, und der Server lehnte sie ab.
    const gefiltert = regeln
      .filter((r) => r.text.trim() !== '')
      .map((r) => ({ ...r, group: r.group.trim() || 'Allgemein' }));

    try {
      if (buch) {
        await api.playbook_aendern(buch.id, {
          name: name.trim(),
          description: text.trim() || null,
        });
        await api.playbook_regeln_setzen(buch.id, gefiltert, verwerfen);
      } else {
        await api.playbook_anlegen({
          name: name.trim(),
          description: text.trim() || null,
          rules: gefiltert,
        });
      }
      onFertig();
    } catch (fehlschlag) {
      const meldung =
        fehlschlag instanceof Error ? fehlschlag.message : 'Speichern fehlgeschlagen';
      // Der Server antwortet mit der Zahl der betroffenen Antworten,
      // bevor er sie wegwirft. Genau diese Zahl gehört auf den Schirm.
      if (meldung.includes('Antworten')) setRueckfrage(meldung);
      else setFehler(meldung);
      setLaeuft(false);
    }
  };

  return (
    <form
      className="td-card"
      style={{ marginTop: 8 }}
      onSubmit={(e) => {
        e.preventDefault();
        void speichern(false);
      }}
    >
      <div style={{ display: 'grid', gap: 12 }}>
        <label style={{ display: 'block' }}>
          <span className="td-label">Name</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="London Breakout"
            style={feldStil}
          />
        </label>
        <label style={{ display: 'block' }}>
          <span className="td-label">Beschreibung</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder="Ausbruch aus der Asien-Range, erste Stunde London."
            style={{ ...feldStil, resize: 'vertical' }}
          />
        </label>
      </div>

      <div style={{ marginTop: 16 }}>
        <span className="td-label">
          Regeln · {regeln.filter((r) => r.checkable).length} abhakbar
        </span>
        <div style={{ marginTop: 4 }}>
          {regeln.map((r, i) => (
            <RegelZeile
              key={r.id ?? `neu-${i}`}
              regel={r}
              erste={i === 0}
              letzte={i === regeln.length - 1}
              pruefungen={pruefungen}
              onAendern={(feld, wert) => setzeRegel(i, feld, wert)}
              onVerschieben={(richtung) => verschiebe(i, richtung)}
              onEntfernen={() =>
                setRegeln((alt) => alt.filter((_, j) => j !== i))
              }
            />
          ))}
        </div>
        <button
          type="button"
          onClick={() =>
            setRegeln((alt) => [
              ...alt,
              {
                // Die Gruppe der letzten Zeile weiterführen: Regeln kommen
                // in Blöcken, und man tippt sie sonst jedes Mal neu.
                group: alt.at(-1)?.group ?? 'Allgemein',
                text: '',
                checkable: true,
                auto_check: null,
                auto_param: null,
              },
            ])
          }
          style={{ ...nebenStil, marginTop: 10 }}
        >
          + Regel hinzufügen
        </button>
      </div>

      {fehler && <Meldung text={fehler} />}

      {rueckfrage && (
        <div
          role="alert"
          style={{
            marginTop: 12,
            padding: '10px 12px',
            fontSize: 12,
            borderLeft: '3px solid var(--td-neg-str)',
            background: 'var(--td-neg-tint)',
            lineHeight: 1.55,
          }}
        >
          <strong style={{ color: 'var(--td-neg)' }}>⚠ {rueckfrage}</strong>
          <p style={{ margin: '6px 0 10px', color: 'var(--td-neutral)' }}>
            Diese Antworten stehen nirgends sonst. Wer die Regel nur umformuliert
            hat, sollte abbrechen und den Text der vorhandenen Regel ändern statt
            sie zu ersetzen — dann bleiben die Häkchen erhalten.
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => {
                setRueckfrage(null);
                void speichern(true);
              }}
              style={{ ...nebenStil, color: 'var(--td-neg)' }}
            >
              Trotzdem streichen
            </button>
            <button
              type="button"
              onClick={() => setRueckfrage(null)}
              style={nebenStil}
            >
              Abbrechen
            </button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
        <button
          type="submit"
          disabled={laeuft}
          style={
            laeuft
              ? { ...knopfStil, background: 'transparent', color: 'var(--td-neutral)' }
              : knopfStil
          }
        >
          {laeuft ? 'speichert …' : buch ? 'Speichern' : 'Playbook anlegen'}
        </button>
        <button type="button" onClick={onAbbrechen} style={nebenStil}>
          Abbrechen
        </button>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ */
/* Eine Zeile in der Liste                                             */
/* ------------------------------------------------------------------ */

function PlaybookZeile({
  buch,
  pruefungen,
  onGeaendert,
}: {
  buch: Playbook;
  pruefungen: Pruefung[];
  onGeaendert: () => void;
}) {
  const [offen, setOffen] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const loeschen = async () => {
    setFehler(null);
    try {
      await api.playbook_loeschen(buch.id);
      onGeaendert();
    } catch (e) {
      setFehler(e instanceof Error ? e.message : 'Löschen fehlgeschlagen');
    }
  };

  const abhakbar = buch.rules.filter((r) => r.checkable).length;

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
        <div style={{ minWidth: 0 }}>
          <span style={{ fontWeight: 600 }}>{buch.name}</span>
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            {' · '}
            {zahl(buch.rules.length)} Regeln, davon {zahl(abhakbar)} abhakbar
            {buch.trade_count > 0
              ? ` · ${zahl(buch.trade_count)} Trades`
              : ' · noch keinem Trade zugeordnet'}
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

      {buch.description && (
        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            margin: '4px 0 0',
            lineHeight: 1.5,
          }}
        >
          {buch.description}
        </p>
      )}

      {!offen && buch.rules.length > 0 && (
        <ul
          style={{
            margin: '6px 0 0',
            paddingLeft: 18,
            fontSize: 11,
            color: 'var(--td-neutral)',
            lineHeight: 1.7,
          }}
        >
          {buch.rules.map((r) => (
            <li key={r.id}>
              {r.text}
              {r.auto_check ? (
                <span style={{ opacity: 0.7 }}> · gemessen</span>
              ) : (
                !r.checkable && <span style={{ opacity: 0.7 }}> · Merksatz</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {fehler && <Meldung text={fehler} />}

      {offen && (
        <>
          <PlaybookFormular
            buch={buch}
            pruefungen={pruefungen}
            onFertig={() => {
              setOffen(false);
              onGeaendert();
            }}
            onAbbrechen={() => setOffen(false)}
          />
          {/* Angeboten wird das Löschen nur, solange kein Trade daran
              hängt. Die Zuordnung ist eine Aussage über vergangene
              Trades und verschwände hier mit. */}
          {buch.trade_count === 0 && (
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
              Dieses ungenutzte Playbook löschen
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function PlaybookSeite() {
  const [runde, setRunde] = useState(0);
  const [neuOffen, setNeuOffen] = useState(false);
  const buecher = useDaten(() => api.playbooks(), [runde]);
  const pruefungen = useDaten(() => api.pruefungen(), []);

  const aktualisieren = () => setRunde((r) => r + 1);

  if (buecher.fehler) {
    return (
      <>
        <PageHead title="Playbooks" />
        <EmptyState cause="sync" detail={buecher.fehler} />
      </>
    );
  }

  const liste = buecher.daten ?? [];

  return (
    <>
      <PageHead
        title="Playbooks"
        sub="Was du zu handeln behauptest — und woran du dich hinterher misst"
      />

      <section className="td-section" style={{ marginTop: 4 }}>
        {buecher.laedt ? (
          <div style={{ color: 'var(--td-neutral)' }}>lädt …</div>
        ) : liste.length === 0 ? (
          <p
            style={{
              fontSize: 12,
              color: 'var(--td-neutral)',
              lineHeight: 1.6,
              margin: 0,
              maxWidth: 560,
            }}
          >
            Noch kein Playbook. Schreib dein erstes Setup auf — die Regeln, die
            erfüllt sein müssen, bevor du einsteigst. Am Trade hakst du sie
            hinterher ab, und die Auswertung sagt dir, ob das Einhalten sich
            rechnet.
          </p>
        ) : (
          <div>
            {liste.map((b) => (
              <PlaybookZeile
                key={b.id}
                buch={b}
                pruefungen={pruefungen.daten ?? []}
                onGeaendert={aktualisieren}
              />
            ))}
          </div>
        )}

        {neuOffen ? (
          <div style={{ marginTop: 14 }}>
            <span className="td-label">Neues Playbook</span>
            <PlaybookFormular
              pruefungen={pruefungen.daten ?? []}
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
            style={{ ...knopfStil, marginTop: 16 }}
          >
            Playbook hinzufügen
          </button>
        )}
      </section>
    </>
  );
}
