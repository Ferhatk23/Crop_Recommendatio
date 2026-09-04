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
import { TAG_ARTEN, type Tag, type TagKind, type TagVorschlag } from '../lib/api';
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
