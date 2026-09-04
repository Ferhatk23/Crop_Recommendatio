'use client';

/**
 * Die Bausteine, mit denen der Nutzer etwas hinterlässt.
 *
 * Alles hier folgt einer Regel: **Der Speicherzustand ist immer sichtbar.**
 *
 * Das klingt nach einem Detail, ist aber der Unterschied zwischen einem
 * Journal, dem man etwas anvertraut, und einem, dem man es nicht mehr
 * anvertraut. Alles andere auf diesem Bildschirm wächst aus den Deals
 * nach: Geht eine Kennzahl verloren, wird sie beim nächsten Abgleich neu
 * gerechnet. Eine Notiz gibt es genau einmal. Wer sie tippt, den Tab
 * schließt und sie später nicht wiederfindet, schreibt keine zweite.
 *
 * Deshalb ausdrücklich speichern statt still im Hintergrund: Ein
 * Auto-Save, das scheitert, sieht genauso aus wie einer, der klappt.
 * Und deshalb eine Warnung beim Verlassen mit ungesicherten Änderungen.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  TAG_ARTEN,
  type Playbook,
  type RegelAntwort,
  type Tag,
  type TagKind,
  type TagVorschlag,
} from '../lib/api';
import { TagChip } from './primitives';

type Zustand = 'rein' | 'geaendert' | 'speichert' | 'gespeichert' | 'fehler';

/* ------------------------------------------------------------------ */
/* Speicheranzeige                                                     */
/* ------------------------------------------------------------------ */

function Anzeige({ zustand, fehler }: { zustand: Zustand; fehler: string | null }) {
  if (zustand === 'rein') return null;

  const text: Record<Exclude<Zustand, 'rein'>, string> = {
    geaendert: 'nicht gespeichert',
    speichert: 'speichert …',
    gespeichert: 'gespeichert',
    fehler: fehler ?? 'nicht gespeichert',
  };

  // Der Fehlerfall bekommt die einzige Farbe, die hier erlaubt ist --
  // und zusätzlich ein Zeichen, damit er nicht nur an der Farbe hängt.
  const istFehler = zustand === 'fehler';

  return (
    <span
      role="status"
      aria-live="polite"
      style={{
        fontSize: 11,
        color: istFehler ? 'var(--td-neg)' : 'var(--td-neutral)',
        fontWeight: istFehler ? 600 : 400,
      }}
    >
      {istFehler ? '⚠ ' : ''}
      {text[zustand]}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Notizfeld                                                           */
/* ------------------------------------------------------------------ */

export function NotizFeld({
  wert,
  onSpeichern,
  platzhalter = 'Was war der Plan? Was ist tatsächlich passiert?',
  zeilen = 6,
  label = 'Notiz',
}: {
  wert: string;
  onSpeichern: (text: string) => Promise<unknown>;
  platzhalter?: string;
  zeilen?: number;
  label?: string;
}) {
  const [text, setText] = useState(wert);
  const [zustand, setZustand] = useState<Zustand>('rein');
  const [fehler, setFehler] = useState<string | null>(null);

  // Der zuletzt vom Server bestätigte Stand. Er ist der Bezugspunkt für
  // "geändert" -- und der Grund, warum die Erfolgsmeldung stehen bleibt.
  const [basis, setBasis] = useState(wert);

  // Kommt von außen ein anderer Wert -- anderer Trade, anderer Tag --,
  // beginnt das Feld von vorn. Ohne das stünde die Notiz des vorigen
  // Trades im Feld des nächsten.
  //
  // Der Vergleich mit `basis` ist dabei entscheidend: Nach dem Speichern
  // reicht die Seite den gespeicherten Wert als neues `wert` herein. Ohne
  // die Bedingung liefe hier der Reset, und die Meldung "gespeichert"
  // verschwände im selben Augenblick, in dem sie erscheinen sollte -- der
  // Nutzer klickte auf Speichern und sähe nichts. Genau das, was diese
  // Komponente verhindern soll.
  useEffect(() => {
    if (wert === basis) return;
    setBasis(wert);
    setText(wert);
    setZustand('rein');
    setFehler(null);
  }, [wert, basis]);

  const offen = zustand === 'geaendert' || zustand === 'fehler';

  // Ungesicherte Änderungen dürfen nicht lautlos verschwinden.
  useEffect(() => {
    if (!offen) return;
    const warnen = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warnen);
    return () => window.removeEventListener('beforeunload', warnen);
  }, [offen]);

  // Der Text, der zuletzt losgeschickt wurde. Das Feld bleibt während
  // des Speicherns tippbar -- es zu sperren fühlte sich hakelig an --,
  // und dann darf am Ende nicht "gespeichert" über einem Text stehen,
  // der nie beim Server war.
  const unterwegs = useRef('');

  const speichern = useCallback(async () => {
    const gesendet = text.trim();
    unterwegs.current = gesendet;
    setZustand('speichert');
    setFehler(null);
    try {
      await onSpeichern(gesendet);
      setBasis(gesendet);
      // Nur bestätigen, wenn seither nichts weitergetippt wurde.
      setZustand((jetzt) =>
        unterwegs.current === gesendet && jetzt === 'speichert'
          ? 'gespeichert'
          : jetzt,
      );
    } catch (e) {
      setZustand('fehler');
      setFehler(e instanceof Error ? e.message : 'Speichern fehlgeschlagen');
    }
  }, [onSpeichern, text]);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
        }}
      >
        <span className="td-label">{label}</span>
        <Anzeige zustand={zustand} fehler={fehler} />
      </div>

      <textarea
        value={text}
        rows={zeilen}
        placeholder={platzhalter}
        aria-label={label}
        onChange={(e) => {
          setText(e.target.value);
          setZustand(e.target.value === basis ? 'rein' : 'geaendert');
        }}
        onKeyDown={(e) => {
          // Strg/Cmd + Enter speichert -- die Hand bleibt auf der Tastatur.
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault();
            void speichern();
          }
        }}
        style={{
          width: '100%',
          marginTop: 6,
          padding: '10px 12px',
          background: 'var(--td-surface)',
          border: '1px solid var(--td-line)',
          borderTop: offen
            ? '3px solid var(--td-accent)'
            : '3px solid transparent',
          color: 'var(--td-text)',
          font: 'inherit',
          fontSize: 13,
          lineHeight: 1.55,
          resize: 'vertical',
        }}
      />

      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          flexWrap: 'wrap',
          marginTop: 6,
        }}
      >
        <button
          onClick={() => void speichern()}
          // `offen` ist nur bei "geändert" oder "fehler" wahr -- während
          // des Speicherns ist die Schaltfläche damit schon aus.
          disabled={!offen}
          style={{
            padding: '7px 14px',
            background: offen ? 'var(--td-accent)' : 'transparent',
            color: offen ? 'var(--td-on-accent)' : 'var(--td-neutral)',
            border: '1px solid var(--td-line)',
            cursor: offen ? 'pointer' : 'default',
            fontWeight: 600,
            fontSize: 12,
          }}
        >
          Speichern
        </button>

        {offen && (
          <button
            onClick={() => {
              setText(basis);
              setZustand('rein');
              setFehler(null);
            }}
            style={{
              padding: '7px 12px',
              background: 'transparent',
              border: '1px solid var(--td-line)',
              color: 'var(--td-neutral)',
              fontSize: 12,
            }}
          >
            Verwerfen
          </button>
        )}

        <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>
          Strg/Cmd + Enter
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tag-Feld                                                            */
/* ------------------------------------------------------------------ */

/**
 * Tags vergeben, mit Vorschlägen aus dem, was schon existiert.
 *
 * Die Vorschläge sind nicht Bequemlichkeit, sondern Datenqualität: Wer
 * bei jedem Trade frei tippt, hat nach einem Monat "Breakout",
 * "breakout" und "Break-out" — und damit drei Zeilen im Setup-Report,
 * wo eine hingehört. Jede für sich sieht plausibel aus.
 */
export function TagFeld({
  tags,
  vorschlaege,
  onSpeichern,
}: {
  tags: Tag[];
  vorschlaege: TagVorschlag[];
  onSpeichern: (tags: { label: string; kind: TagKind }[]) => Promise<unknown>;
}) {
  const [aktuell, setAktuell] = useState<{ label: string; kind: TagKind }[]>(
    tags.map((t) => ({ label: t.label, kind: t.kind })),
  );
  const [eingabe, setEingabe] = useState('');
  const [art, setArt] = useState<TagKind>('setup');
  const [zustand, setZustand] = useState<Zustand>('rein');
  const [fehler, setFehler] = useState<string | null>(null);
  const feld = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setAktuell(tags.map((t) => ({ label: t.label, kind: t.kind })));
    setZustand('rein');
    setFehler(null);
  }, [tags]);

  const sichern = async (liste: { label: string; kind: TagKind }[]) => {
    setAktuell(liste);
    setZustand('speichert');
    setFehler(null);
    try {
      await onSpeichern(liste);
      setZustand('gespeichert');
    } catch (e) {
      setZustand('fehler');
      setFehler(e instanceof Error ? e.message : 'Speichern fehlgeschlagen');
      // Zurück auf den letzten bestätigten Stand. Eine Oberfläche, die
      // einen Tag zeigt, den der Server nicht hat, lügt.
      setAktuell(tags.map((t) => ({ label: t.label, kind: t.kind })));
    }
  };

  const hinzu = (label: string, kind: TagKind) => {
    const text = label.trim();
    if (!text) return;
    if (aktuell.some((t) => t.label === text && t.kind === kind)) {
      setEingabe('');
      return;
    }
    void sichern([...aktuell, { label: text, kind }]);
    setEingabe('');
    feld.current?.focus();
  };

  const weg = (label: string, kind: TagKind) =>
    void sichern(aktuell.filter((t) => !(t.label === label && t.kind === kind)));

  // Vorschläge: passend zur Art, noch nicht vergeben, häufigste zuerst.
  const passend = vorschlaege
    .filter(
      (v) =>
        v.kind === art &&
        !aktuell.some((t) => t.label === v.label && t.kind === v.kind) &&
        (eingabe.trim() === '' ||
          v.label.toLowerCase().includes(eingabe.trim().toLowerCase())),
    )
    .slice(0, 8);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 10,
        }}
      >
        <span className="td-label">Tags</span>
        <Anzeige zustand={zustand} fehler={fehler} />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 6,
          flexWrap: 'wrap',
          marginTop: 8,
          minHeight: 30,
          alignItems: 'center',
        }}
      >
        {aktuell.length ? (
          aktuell.map((t) => (
            <TagChip
              key={`${t.kind}:${t.label}`}
              tag={t}
              onRemove={() => weg(t.label, t.kind)}
            />
          ))
        ) : (
          <span style={{ color: 'var(--td-neutral)', fontSize: 12 }}>
            Noch keine Tags vergeben.
          </span>
        )}
      </div>

      <div
        style={{
          display: 'flex',
          gap: 6,
          flexWrap: 'wrap',
          marginTop: 10,
          alignItems: 'center',
        }}
      >
        <select
          value={art}
          onChange={(e) => setArt(e.target.value as TagKind)}
          aria-label="Art des Tags"
          style={{ fontSize: 12 }}
        >
          {TAG_ARTEN.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>

        <input
          ref={feld}
          value={eingabe}
          onChange={(e) => setEingabe(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              hinzu(eingabe, art);
            }
          }}
          placeholder="Tag eingeben und Enter"
          aria-label="Neuer Tag"
          maxLength={80}
          style={{
            flex: '1 1 180px',
            minWidth: 0,
            padding: '7px 10px',
            background: 'var(--td-surface)',
            border: '1px solid var(--td-line)',
            color: 'var(--td-text)',
            font: 'inherit',
            fontSize: 12,
          }}
        />

        <button
          onClick={() => hinzu(eingabe, art)}
          disabled={!eingabe.trim()}
          style={{
            padding: '7px 12px',
            background: eingabe.trim() ? 'var(--td-accent)' : 'transparent',
            color: eingabe.trim() ? 'var(--td-on-accent)' : 'var(--td-neutral)',
            border: '1px solid var(--td-line)',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          Hinzufügen
        </button>
      </div>

      {passend.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <span style={{ fontSize: 10, color: 'var(--td-neutral)' }}>
            Schon vergeben:
          </span>
          <div
            style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}
          >
            {passend.map((v) => (
              <button
                key={v.id}
                onClick={() => hinzu(v.label, v.kind)}
                style={{
                  padding: '3px 8px',
                  fontSize: 11,
                  background: 'transparent',
                  border: '1px dotted var(--td-line)',
                  color: 'var(--td-neutral)',
                }}
              >
                {v.label}
                <span style={{ opacity: 0.6 }}> · {v.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Stimmung                                                            */
/* ------------------------------------------------------------------ */

const STIMMUNGEN = [
  { wert: 1, zeichen: '▁', text: 'sehr schlecht' },
  { wert: 2, zeichen: '▃', text: 'schlecht' },
  { wert: 3, zeichen: '▅', text: 'neutral' },
  { wert: 4, zeichen: '▆', text: 'gut' },
  { wert: 5, zeichen: '█', text: 'sehr gut' },
];

/**
 * Die Verfassung des Tages, in fünf Stufen.
 *
 * Bewusst ohne Grün und Rot: Ein guter Tag im Kopf ist kein Gewinn, und
 * ein mieser kein Verlust. Genau darin liegt der Nutzen der Angabe — wer
 * sie einfärbt wie das Ergebnis, kann die beiden nie mehr gegeneinander
 * lesen. Die Stufe steckt in der Höhe des Balkens, nicht in der Farbe.
 */
export function StimmungsWahl({
  wert,
  onWahl,
}: {
  wert: number | null;
  onWahl: (wert: number | null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
      {STIMMUNGEN.map((s) => {
        const an = wert === s.wert;
        return (
          <button
            key={s.wert}
            onClick={() => onWahl(an ? null : s.wert)}
            aria-label={`Stimmung ${s.text}`}
            aria-pressed={an}
            title={s.text}
            style={{
              width: 32,
              height: 32,
              display: 'grid',
              placeItems: 'center',
              fontSize: 14,
              lineHeight: 1,
              background: an ? 'var(--td-accent)' : 'transparent',
              color: an ? 'var(--td-on-accent)' : 'var(--td-neutral)',
              border: '1px solid var(--td-line)',
            }}
          >
            {s.zeichen}
          </button>
        );
      })}
      <span style={{ fontSize: 11, color: 'var(--td-neutral)', marginLeft: 4 }}>
        {wert ? STIMMUNGEN.find((s) => s.wert === wert)?.text : 'keine Angabe'}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Playbook und Regel-Häkchen                                          */
/* ------------------------------------------------------------------ */

/**
 * Das Playbook eines Trades und die Antworten auf seine Regeln.
 *
 * **Drei Zustände, nicht zwei.** Eine Regel ist eingehalten, gebrochen —
 * oder unbeantwortet. Der dritte ist kein Zwischending, sondern der
 * häufigste: Man geht einen Trade durch, wenn man Zeit hat, nicht in dem
 * Moment, in dem er einläuft. Gäbe es nur ein Kästchen an oder aus, wäre
 * ein Trade, den man nie angesehen hat, von einem mit lauter Regelbrüchen
 * nicht zu unterscheiden — und die Regeltreue-Quote bestrafte den, der
 * noch nicht dazugekommen ist.
 *
 * **Die Auswahl des Playbooks speichert sofort, die Häkchen nicht.** Das
 * ist kein Widerspruch zur Regel „gespeichert wird ausdrücklich", sondern
 * ihre Voraussetzung: Erst wenn das Playbook am Trade steht, nimmt der
 * Server überhaupt Antworten auf seine Regeln an. Ein Klick, ein
 * eindeutiges Ergebnis, sichtbar bestätigt.
 */
function RegelKnopf({
  zeichen,
  beschriftung,
  gedrueckt,
  onClick,
}: {
  zeichen: string;
  beschriftung: string;
  gedrueckt: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={beschriftung}
      aria-pressed={gedrueckt}
      onClick={onClick}
      style={{
        minWidth: 34,
        minHeight: 30,
        border: '1px solid var(--td-line)',
        background: gedrueckt ? 'var(--td-accent)' : 'transparent',
        color: gedrueckt ? 'var(--td-on-accent)' : 'var(--td-neutral)',
        fontWeight: gedrueckt ? 700 : 400,
        fontSize: 13,
      }}
    >
      {zeichen}
    </button>
  );
}

/** Ein vergleichbarer Abdruck des Antwortstands. Sortiert, also stabil. */
function schluesselVon(playbookId: number | null, antworten: RegelAntwort[]) {
  return `${playbookId ?? 0}:${antworten
    .map((a) => `${a.rule_id}${a.checked ? '1' : '0'}`)
    .sort()
    .join(',')}`;
}

export function PlaybookFeld({
  playbooks,
  playbookId,
  antworten,
  onPlaybookSetzen,
  onSpeichern,
}: {
  playbooks: Playbook[];
  playbookId: number | null;
  antworten: RegelAntwort[];
  onPlaybookSetzen: (id: number | null) => Promise<unknown>;
  onSpeichern: (antworten: RegelAntwort[]) => Promise<unknown>;
}) {
  const [aktuell, setAktuell] = useState<Map<number, boolean>>(
    new Map(antworten.map((a) => [a.rule_id, a.checked])),
  );
  const [zustand, setZustand] = useState<Zustand>('rein');
  const [fehler, setFehler] = useState<string | null>(null);
  const [wechselt, setWechselt] = useState(false);

  // Kommt von außen ein anderer Trade — oder ein anderes Playbook am
  // selben Trade —, beginnen die Häkchen von vorn. Der Schlüssel enthält
  // die Zuordnung, weil ein Wechsel eine andere Regelliste bedeutet.
  //
  // Der Vergleich mit `basis` ist derselbe Kniff wie beim Notizfeld, und
  // aus demselben Grund: Nach dem Speichern reicht die Seite den
  // gespeicherten Stand als neues `antworten` herein. Ohne die Bedingung
  // liefe hier der Reset, und "gespeichert" verschwände in dem
  // Augenblick, in dem es erscheinen soll — man klickte auf Speichern und
  // sähe nichts.
  const schluessel = schluesselVon(playbookId, antworten);
  const [basis, setBasis] = useState(schluessel);
  useEffect(() => {
    if (schluessel === basis) return;
    setBasis(schluessel);
    setAktuell(new Map(antworten.map((a) => [a.rule_id, a.checked])));
    setZustand('rein');
    setFehler(null);
  }, [schluessel, basis, antworten]);

  const buch = playbooks.find((p) => p.id === playbookId) ?? null;
  const offen = zustand === 'geaendert' || zustand === 'fehler';

  const setze = (rule_id: number, wert: boolean | null) => {
    setAktuell((alt) => {
      const neu = new Map(alt);
      if (wert === null) neu.delete(rule_id);
      else neu.set(rule_id, wert);
      return neu;
    });
    setZustand('geaendert');
  };

  const speichern = async () => {
    const gesendet = [...aktuell.entries()].map(([rule_id, checked]) => ({
      rule_id,
      checked,
    }));
    setZustand('speichert');
    setFehler(null);
    try {
      await onSpeichern(gesendet);
      // Den Bezugspunkt mitziehen, *bevor* der neue Stand als Prop
      // hereinkommt — sonst setzt der Effekt oben die Meldung sofort
      // wieder zurück.
      setBasis(schluesselVon(playbookId, gesendet));
      setZustand('gespeichert');
    } catch (e) {
      setZustand('fehler');
      setFehler(e instanceof Error ? e.message : 'Speichern fehlgeschlagen');
    }
  };

  const wechseln = async (id: number | null) => {
    setWechselt(true);
    setFehler(null);
    try {
      await onPlaybookSetzen(id);
    } catch (e) {
      setFehler(e instanceof Error ? e.message : 'Zuordnung fehlgeschlagen');
      setZustand('fehler');
    } finally {
      setWechselt(false);
    }
  };

  const abhakbar = buch ? buch.rules.filter((r) => r.checkable) : [];
  const beantwortet = abhakbar.filter((r) => aktuell.has(r.id)).length;

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          columnGap: 10,
          rowGap: 2,
        }}
      >
        <span className="td-label">Playbook</span>
        {wechselt ? (
          <span role="status" style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            speichert …
          </span>
        ) : (
          <Anzeige zustand={zustand} fehler={fehler} />
        )}
      </div>

      <select
        aria-label="Playbook"
        value={playbookId ?? ''}
        disabled={wechselt}
        onChange={(e) =>
          void wechseln(e.target.value === '' ? null : Number(e.target.value))
        }
        style={{
          width: '100%',
          maxWidth: 420,
          marginTop: 6,
          padding: '8px 10px',
          background: 'var(--td-surface)',
          border: '1px solid var(--td-line)',
          color: 'var(--td-text)',
          font: 'inherit',
          fontSize: 13,
        }}
      >
        <option value="">— keinem Playbook zugeordnet —</option>
        {playbooks.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>

      {playbooks.length === 0 && (
        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            margin: '6px 0 0',
            lineHeight: 1.55,
          }}
        >
          Noch kein Playbook angelegt. Unter Playbooks schreibst du auf, was
          erfüllt sein muss, bevor du einsteigst — hier hakst du es hinterher ab.
        </p>
      )}

      {buch && buch.rules.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <span className="td-label">
            Regeln · {beantwortet} von {abhakbar.length} beantwortet
          </span>

          <div style={{ marginTop: 4 }}>
            {buch.rules.map((r, i) => {
              const vorige = i > 0 ? buch.rules[i - 1] : null;
              const neueGruppe = vorige === null || vorige.group !== r.group;
              const wert = aktuell.get(r.id);
              return (
                <div key={r.id}>
                  {neueGruppe && (
                    <div
                      style={{
                        fontSize: 10,
                        letterSpacing: '0.06em',
                        textTransform: 'uppercase',
                        color: 'var(--td-neutral)',
                        marginTop: i === 0 ? 4 : 12,
                        marginBottom: 2,
                      }}
                    >
                      {r.group}
                    </div>
                  )}
                  {r.checkable ? (
                    <div
                      role="group"
                      aria-label={r.text}
                      style={{
                        display: 'flex',
                        gap: 8,
                        alignItems: 'center',
                        padding: '5px 0',
                        borderTop: '1px solid var(--td-line)',
                      }}
                    >
                      {/* Zwei Knöpfe statt eines Kästchens: Der dritte
                          Zustand — noch nicht beantwortet — hat sonst
                          keine eigene Darstellung. Ein zweiter Klick auf
                          den gedrückten Knopf führt dorthin zurück.

                          Beide tragen dieselbe Farbe, wenn sie gedrückt
                          sind. Ein grünes Häkchen und ein rotes Kreuz
                          lägen nahe, verstiessen aber gegen die erste
                          Regel des Entwurfs: Grün und Rot gehören dem
                          Ergebnis, und ein Regelbruch ist kein Verlust in
                          Euro. Wer sie hier ausleiht, macht sie eine
                          Spur beliebiger — und irgendwann sagt Rot auf
                          dem Bildschirm nichts mehr. Das Zeichen selbst
                          trägt die Bedeutung; die Farbe sagt nur, dass
                          geantwortet wurde. */}
                      <RegelKnopf
                        zeichen="✓"
                        beschriftung={`${r.text}: eingehalten`}
                        gedrueckt={wert === true}
                        onClick={() => setze(r.id, wert === true ? null : true)}
                      />
                      <RegelKnopf
                        zeichen="✗"
                        beschriftung={`${r.text}: gebrochen`}
                        gedrueckt={wert === false}
                        onClick={() => setze(r.id, wert === false ? null : false)}
                      />
                      <span style={{ fontSize: 12, lineHeight: 1.45 }}>
                        {r.text}
                      </span>
                      {wert === undefined && (
                        <span
                          style={{
                            marginLeft: 'auto',
                            fontSize: 10,
                            color: 'var(--td-neutral)',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          offen
                        </span>
                      )}
                    </div>
                  ) : (
                    /* Merksatz: nichts zum Abhaken, aber er gehört auf den
                       Schirm — man liest ihn beim Durchgehen mit. */
                    <div
                      style={{
                        padding: '5px 0 5px 2px',
                        borderTop: '1px solid var(--td-line)',
                        fontSize: 12,
                        color: 'var(--td-neutral)',
                        lineHeight: 1.45,
                      }}
                    >
                      {r.text}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              flexWrap: 'wrap',
              marginTop: 10,
            }}
          >
            <button
              onClick={() => void speichern()}
              disabled={!offen}
              style={{
                padding: '7px 14px',
                background: offen ? 'var(--td-accent)' : 'transparent',
                color: offen ? 'var(--td-on-accent)' : 'var(--td-neutral)',
                border: '1px solid var(--td-line)',
                cursor: offen ? 'pointer' : 'default',
                fontWeight: 600,
                fontSize: 12,
              }}
            >
              Häkchen speichern
            </button>
            {offen && (
              <button
                onClick={() => {
                  setAktuell(new Map(antworten.map((a) => [a.rule_id, a.checked])));
                  setZustand('rein');
                  setFehler(null);
                }}
                style={{
                  padding: '7px 12px',
                  background: 'transparent',
                  border: '1px solid var(--td-line)',
                  color: 'var(--td-neutral)',
                  fontSize: 12,
                }}
              >
                Verwerfen
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
