/**
 * Der Regel-Puffer-Balken.
 *
 * Laut Übergabe der erste Baustein, der gebaut wird — und der Grund ist
 * gut: Für einen Prop-Trader ist das die wichtigste Information im
 * Produkt. Ein gerissenes Tageslimit kostet das Konto, eine mittelmäßige
 * Trefferquote kostet nur Zeit.
 *
 * Der Balken füllt sich Richtung Gefahr. Ab der Warnschwelle liegt eine
 * Schraffur darüber — ein zweiter Kanal neben der Farbe, damit die Warnung
 * auch ohne Rot-Grün-Unterscheidung ankommt.
 */

import type { Buffer } from '../lib/api';
import { STRICH, betrag, prozent } from '../lib/format';

export function RuleBuffer({
  buffer,
  /** Konsistenz ist ein Anteil, kein Geldbetrag. */
  alsAnteil = false,
  compact = false,
}: {
  buffer: Buffer;
  alsAnteil?: boolean;
  compact?: boolean;
}) {
  const formatiere = (w: number | null) =>
    w === null ? STRICH : alsAnteil ? prozent(w) : betrag(w);

  // Ohne hinterlegtes Limit gibt es keinen Puffer, sondern einen Grund.
  // Ein geschätzter Puffer wäre gefährlicher als gar keiner.
  if (!buffer.measurable) {
    return (
      <div
        style={{
          background: 'var(--td-surface)',
          padding: compact ? '10px 12px' : '14px 16px',
          borderTop: '3px solid var(--td-neutral)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
          }}
        >
          <span className="td-label">{buffer.label}</span>
          <span style={{ color: 'var(--td-neutral)', fontSize: 13 }}>{STRICH}</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--td-neutral)', marginTop: 4 }}>
          {buffer.reason ?? 'nicht messbar'}
        </div>
      </div>
    );
  }

  const anteil = buffer.ratio ?? 0;
  const gefuellt = Math.min(1, anteil);
  const warnAb = buffer.warn_at ?? 0.8;
  const gerissen = buffer.state === 'gerissen';
  const warnt = buffer.state === 'warnung';

  const balkenFarbe = gerissen
    ? 'var(--td-neg-str)'
    : warnt
      ? 'var(--td-neg)'
      : 'var(--td-accent)';

  return (
    <div
      style={{
        background: 'var(--td-surface)',
        padding: compact ? '10px 12px' : '14px 16px',
        borderTop: `3px solid ${
          gerissen || warnt ? 'var(--td-neg-str)' : 'var(--td-accent)'
        }`,
      }}
    >
      {/* Nebeneinander, solange es passt. In einer schmalen Rasterzelle
          brauchen Beschriftung und Zahl zusammen mehr Platz, als die
          Zelle hat -- dann rutscht die Zahl auf eine eigene Zeile. Sie
          zu verkleinern oder abzuschneiden wäre schlechter: Ein Limit,
          von dem man nur "5.575,4" sieht, ist keine Angabe mehr. */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          columnGap: 10,
        }}
      >
        <span className="td-label">{buffer.label}</span>
        <span
          className="td-display"
          style={{
            fontSize: compact ? 17 : 22,
            color: gerissen || warnt ? 'var(--td-neg)' : 'var(--td-text)',
          }}
        >
          {formatiere(buffer.remaining)}
        </span>
      </div>

      <div
        style={{
          fontSize: 11,
          color: 'var(--td-neutral)',
          marginTop: 2,
          marginBottom: 8,
        }}
      >
        {gerissen ? 'Limit erreicht' : 'noch übrig'} · {formatiere(buffer.used)} von{' '}
        {formatiere(buffer.limit)} verbraucht
      </div>

      {/* Der Balken. Die Schraffur beginnt an der Warnschwelle und liegt
          über der Spur, nicht über der Füllung — so sieht man auch die
          Zone, in die man noch nicht hineingelaufen ist. */}
      <div
        role="meter"
        aria-valuenow={Math.round(anteil * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${buffer.label}: ${Math.round(anteil * 100)} Prozent verbraucht`}
        style={{
          position: 'relative',
          height: 10,
          background: 'var(--td-sunk)',
          border: '1px solid var(--td-line)',
          overflow: 'hidden',
        }}
      >
        <div
          className="td-hatch"
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            left: `${warnAb * 100}%`,
            opacity: 0.35,
          }}
        />
        <div
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            right: `${(1 - gefuellt) * 100}%`,
            background: balkenFarbe,
            transition: 'right var(--td-dur-base) var(--td-ease)',
          }}
        />
        <div
          aria-hidden
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${warnAb * 100}%`,
            width: 1,
            background: 'var(--td-neg-str)',
          }}
        />
      </div>

      {/* `space-between` verteilt nur den *freien* Platz. Ist keiner da,
          stoßen die beiden Angaben ohne Lücke aneinander und lesen sich
          als ein Wort ("0 % verbrauchtWarnung ab 80 %"). Der Spaltenrand
          hält sie auseinander, `flex-wrap` bricht sie bei Bedarf um, und
          `nowrap` je Angabe verhindert, dass das Prozentzeichen allein
          in der nächsten Zeile landet. */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          columnGap: 10,
          rowGap: 2,
          fontSize: 10,
          color: 'var(--td-neutral)',
          marginTop: 4,
        }}
      >
        <span style={{ whiteSpace: 'nowrap' }}>
          {prozent(anteil, 0)} verbraucht
        </span>
        <span style={{ whiteSpace: 'nowrap' }}>
          Warnung ab {prozent(warnAb, 0)}
        </span>
      </div>
    </div>
  );
}

/**
 * Der Endzustand: Das Konto ist weg.
 *
 * Kein roter Balken mehr, sondern eine Fläche, die den ganzen Screen
 * einnimmt. Ein gerissenes Limit ist kein Statuswert, sondern das Ende
 * dieses Kontos — und die Oberfläche soll das nicht relativieren.
 */
export function AccountLost({
  buffer,
  accountLabel,
}: {
  buffer: Buffer;
  accountLabel: string;
}) {
  return (
    <div
      style={{
        background: 'var(--td-neg-tint)',
        borderTop: '4px solid var(--td-neg-str)',
        padding: '26px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <span className="td-label" style={{ color: 'var(--td-neg)' }}>
        Konto verloren
      </span>
      <span className="td-display" style={{ fontSize: 30, color: 'var(--td-neg)' }}>
        {buffer.label} gerissen
      </span>
      <span style={{ maxWidth: '56ch', color: 'var(--td-text)' }}>
        {accountLabel} hat das Limit von {betrag(buffer.limit)} erreicht
        ({betrag(buffer.used)} verbraucht). Die Historie bleibt erhalten und
        auswertbar — das Konto nimmt aber keine neuen Trades mehr auf.
      </span>
    </div>
  );
}
