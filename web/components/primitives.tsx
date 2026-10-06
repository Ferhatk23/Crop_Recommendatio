/**
 * Die kleinen Bausteine.
 *
 * Alle Ergebnisdarstellungen gehen durch `outcome()` — Farbe, Vorzeichen
 * und Regelposition kommen aus einer Quelle, damit sie nicht auseinander
 * driften.
 */

import type { CSSProperties, ReactNode } from 'react';
import { outcome } from '../lib/outcome';
import { STRICH, geld, prozent } from '../lib/format';
import type { Tag } from '../lib/api';

/* ------------------------------------------------------------------ */
/* 1 · KPI-Kachel                                                      */
/* ------------------------------------------------------------------ */

export function KpiTile({
  label,
  value,
  compare,
  period,
  reason,
  outcomeValue,
  large,
}: {
  label: string;
  /** Bereits formatiert — die Umrechnung gehört zum Umschalter. */
  value: string;
  compare?: string;
  /** Jede Zahl trägt ihren Zeitraum. "+1.284 €" allein ist keine Aussage. */
  period?: string;
  /** Pflicht, wenn kein Wert vorliegt. */
  reason?: string;
  /** Rohwert nur für Farbe und Regelposition. */
  outcomeValue?: number | null;
  large?: boolean;
}) {
  const o = outcome(outcomeValue, reason);
  const leer = value === STRICH;
  // Nicht jede Kennzahl ist ein Ergebnis: Eine Trefferquote hat kein
  // Vorzeichen. Ohne Ergebnisbezug steht die Zahl in Tinte, nicht im
  // Grau der fehlenden Werte -- sonst sieht ein vorhandener Wert aus
  // wie ein nicht messbarer.
  const farbe = leer
    ? 'var(--td-neutral)'
    : outcomeValue === null || outcomeValue === undefined
      ? 'var(--td-text)'
      : o.cssColor;

  return (
    <div
      className={large ? `${o.ruleClass} td-kpi-gross` : o.ruleClass}
      style={{
        background: 'var(--td-surface)',
        padding: large ? '18px 18px 20px' : '12px 14px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        // Die Mindesthöhe der Leitkacheln steht im Stylesheet, weil sie
        // von der Breite abhängt; hier bliebe sie starr.
        minHeight: large ? undefined : 96,
      }}
    >
      <span className="td-label">{label}</span>
      <span
        className="td-display"
        style={{
          fontSize: large ? 38 : 22,
          color: farbe,
          // Zahl und Währung gehören zusammen. Ohne das bricht
          // "+24.129,46 €" um und das € steht allein in der zweiten Zeile.
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </span>
      {period && (
        <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>{period}</span>
      )}
      {compare && (
        <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>{compare}</span>
      )}
      {leer && reason && (
        <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>{reason}</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 2 · Richtungs-Pille                                                 */
/* ------------------------------------------------------------------ */

/**
 * Long gefüllt, Short umrandet — beides in Tinte.
 * Bewusst nie grün oder rot: Die Farben gehören dem Ergebnis, und eine
 * rote Short-Pille neben einer roten Verlustzahl macht beide unlesbar.
 */
export function DirectionPill({ direction }: { direction: 'long' | 'short' }) {
  const long = direction === 'long';
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 7px',
        fontSize: 10,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        fontWeight: 600,
        border: '1px solid var(--td-accent)',
        background: long ? 'var(--td-accent)' : 'transparent',
        color: long ? 'var(--td-on-accent)' : 'var(--td-accent)',
        whiteSpace: 'nowrap',
      }}
    >
      {long ? 'Long' : 'Short'}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* 3 · Tag-Chip                                                        */
/* ------------------------------------------------------------------ */

/** Drei Sorten, an der Form unterscheidbar — nicht nur an der Farbe. */
export function TagChip({
  tag,
  onRemove,
}: {
  tag: Pick<Tag, 'label' | 'kind'>;
  onRemove?: () => void;
}) {
  const stil: Record<Tag['kind'], CSSProperties> = {
    setup: { border: '1px solid var(--td-accent)', background: 'transparent' },
    fehler: {
      border: '1px solid var(--td-accent)',
      background: 'var(--td-neutral-t)',
    },
    emotion: {
      border: '1px dashed var(--td-accent)',
      background: 'transparent',
    },
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: onRemove ? '4px 4px 4px 8px' : '3px 8px',
        fontSize: 11,
        color: 'var(--td-text)',
        whiteSpace: 'nowrap',
        ...stil[tag.kind],
      }}
    >
      {tag.label}
      {onRemove && (
        <button
          onClick={onRemove}
          aria-label={`${tag.label} entfernen`}
          style={{
            minHeight: 'auto',
            width: 24,
            height: 24,
            display: 'grid',
            placeItems: 'center',
            fontSize: 12,
            lineHeight: 1,
          }}
        >
          ✕
        </button>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* 4 · Leerzustand                                                     */
/* ------------------------------------------------------------------ */

/**
 * Sagt, *warum* nichts da ist, und bietet den Ausweg an.
 *
 * Drei Ursachen, die niemals gleich aussehen dürfen: der Filter ist zu
 * eng, es gibt wirklich keine Daten, oder die Anbindung ist still. Der
 * letzte Fall ist der gefährliche — ein stiller Sync-Ausfall darf nicht
 * wie ein ruhiger Handelstag wirken.
 */
export function EmptyState({
  cause,
  detail,
  action,
}: {
  cause: 'filter' | 'keine-daten' | 'sync';
  detail?: string;
  action?: ReactNode;
}) {
  const texte = {
    filter: {
      titel: 'Keine Trades im gewählten Ausschnitt',
      hinweis: 'Der Filter ist zu eng gesetzt.',
    },
    'keine-daten': {
      titel: 'Noch keine Trades',
      hinweis: 'Sobald der erste Trade geschlossen ist, steht er hier.',
    },
    sync: {
      titel: 'Die Übernahme ist still',
      hinweis:
        'Es kommen keine Daten mehr an. Das sieht aus wie ein ruhiger Tag, ist aber keiner.',
    },
  }[cause];

  return (
    <div
      style={{
        background: 'var(--td-sunk)',
        padding: '28px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        borderTop:
          cause === 'sync'
            ? '3px solid var(--td-neg-str)'
            : '2px solid var(--td-divider)',
      }}
    >
      <span className="td-display" style={{ fontSize: 17 }}>
        {texte.titel}
      </span>
      <span style={{ color: 'var(--td-neutral)', maxWidth: '52ch' }}>
        {detail ?? texte.hinweis}
      </span>
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 5 · Regel-Checkliste                                                */
/* ------------------------------------------------------------------ */

/**
 * Erfüllung als Bruch, nie als Prozent — "4 von 6" liest sich schneller
 * als "67 %", und es sagt zusätzlich, wie viele Regeln es überhaupt gibt.
 */
export function RuleChecklist({
  rules,
}: {
  rules: { text: string; group: string; checkable: boolean; done: boolean }[];
}) {
  // Nur prüfbare Regeln zählen in die Quote. Selbstberichtete werden
  // angezeigt, aber herausgehalten — sonst misst man Ehrlichkeit und
  // nennt es Disziplin.
  const pruefbar = rules.filter((r) => r.checkable);
  const erfuellt = pruefbar.filter((r) => r.done).length;

  const gruppen = rules.reduce<Record<string, typeof rules>>((acc, r) => {
    (acc[r.group] ??= []).push(r);
    return acc;
  }, {});

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          paddingBottom: 8,
        }}
      >
        <span className="td-label">Regeltreue</span>
        <span className="td-display" style={{ fontSize: 17 }}>
          {erfuellt} von {pruefbar.length}
        </span>
      </div>
      {Object.entries(gruppen).map(([gruppe, liste]) => (
        <div key={gruppe} style={{ borderTop: '1px solid var(--td-line)' }}>
          <div className="td-label" style={{ padding: '8px 0 4px' }}>
            {gruppe}
          </div>
          {liste.map((r, i) => (
            <div
              key={i}
              className="td-tap"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 0',
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 16,
                  height: 16,
                  flexShrink: 0,
                  border: `1px ${r.checkable ? 'solid' : 'dashed'} var(--td-accent)`,
                  background: r.done ? 'var(--td-accent)' : 'transparent',
                  color: 'var(--td-on-accent)',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 11,
                  lineHeight: 1,
                }}
              >
                {r.done ? '✓' : ''}
              </span>
              <span style={{ flex: 1 }}>{r.text}</span>
              {!r.checkable && (
                <span className="td-label" style={{ fontSize: 9 }}>
                  selbst berichtet
                </span>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 6 · Herzschlag der Übernahme                                        */
/* ------------------------------------------------------------------ */

/**
 * Die Statuszeile des ganzen Produkts.
 *
 * Alles kommt aus MT5 — der Nutzer tippt nichts ein außer Notizen und
 * Tags. Fällt die Anbindung still aus, zeigt die App weiter Zahlen, nur
 * eben veraltete. Deshalb steht der Zustand dauerhaft in der Navigation
 * und nicht in einer Meldung, die man wegklickt.
 */
export function SyncHeartbeat({
  sync,
  kompakt,
}: {
  sync: { state: string; minutes_ago: number | null; last_error: string | null };
  kompakt?: boolean;
}) {
  // Drei Stufen, nicht zwei. Ein Abgleich von vor 40 Minuten ist nicht
  // frisch, aber auch kein Alarm — wer dafür schon die rote Regel zieht,
  // stumpft sie ab, und dann sieht man den echten Ausfall nicht mehr.
  const stufe =
    sync.state === 'gesund'
      ? 'ok'
      : sync.state === 'verzoegert'
        ? 'alt'
        : 'aus';

  const text =
    sync.state === 'nie'
      ? 'noch nie abgeglichen'
      : sync.state === 'fehler'
        ? 'Abgleich fehlgeschlagen'
        : sync.minutes_ago === null
          ? 'unbekannt'
          : sync.minutes_ago < 1
            ? 'gerade eben'
            : sync.minutes_ago < 60
              ? `vor ${sync.minutes_ago} min`
              : `seit ${Math.floor(sync.minutes_ago / 60)} h still`;

  const punktFarbe =
    stufe === 'ok'
      ? 'var(--td-pos)'
      : stufe === 'alt'
        ? 'var(--td-neutral)'
        : 'var(--td-neg-str)';

  return (
    <div
      title={sync.last_error ?? undefined}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: kompakt ? '6px 0' : '10px 12px',
        background: kompakt ? 'transparent' : 'var(--td-surface)',
        // Die rote Regel bleibt dem echten Ausfall vorbehalten.
        borderTop: stufe === 'aus' ? '3px solid var(--td-neg-str)' : undefined,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 7,
          height: 7,
          flexShrink: 0,
          background: punktFarbe,
          // Zweiter Kanal: der offene Ring heißt "nicht frisch".
          boxShadow: stufe === 'alt' ? 'inset 0 0 0 1px var(--td-surface)' : undefined,
        }}
      />
      <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
        Abgleich {text}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 7 · Wert mit Grund                                                  */
/* ------------------------------------------------------------------ */

/** Ein Zahlenfeld, das bei fehlendem Wert den Grund nennt statt einer Null. */
export function Wert({
  value,
  formatted,
  reason,
  size = 13,
}: {
  value: number | null | undefined;
  formatted: string;
  reason?: string;
  size?: number;
}) {
  const o = outcome(value, reason);
  return (
    <span
      title={o.empty ? o.reason : undefined}
      style={{
        fontSize: size,
        color: o.empty ? 'var(--td-neutral)' : o.cssColor,
        fontWeight: o.empty ? 400 : 600,
      }}
    >
      {formatted}
    </span>
  );
}

export { geld, prozent };
