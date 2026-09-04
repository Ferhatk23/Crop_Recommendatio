'use client';

/**
 * Die Anmeldung.
 *
 * Sie steht vor allem anderen — nicht als Seite mit eigener Adresse,
 * sondern als das, was das Gerüst zeigt, solange niemand angemeldet ist.
 * Der Grund ist praktisch: Ein Journal wird vom Sperrbildschirm aus
 * geöffnet, per Lesezeichen mitten in einer Ansicht. Eine Weiterleitung
 * auf `/login` und zurück verliert dabei jedes Mal die Stelle, an der man
 * war. Wer sich hier anmeldet, steht danach genau dort.
 *
 * Was hier bewusst fehlt:
 *
 * * **Kein „Registrieren".** Ein selbstbetriebenes Journal für eine
 *   Person braucht keins, und ein offenes Anmeldeformular im Netz ist
 *   eine Einladung. Nutzer legt `scripts/nutzer.py` an.
 * * **Kein „Passwort vergessen".** Dafür bräuchte es einen Mailversand,
 *   und der ist bei Selbstbetrieb entweder nicht da oder die
 *   unsicherste Stelle im ganzen Aufbau. Wer sein Passwort verliert,
 *   setzt am Rechner ein neues.
 */

import { useState } from 'react';
import { useApp } from './AppState';
import { api } from '../lib/api';

export function Anmeldung() {
  const { neuLaden } = useApp();
  const [email, setEmail] = useState('');
  const [passwort, setPasswort] = useState('');
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const absenden = async (e: React.FormEvent) => {
    e.preventDefault();
    if (laeuft) return;
    setLaeuft(true);
    setFehler(null);
    try {
      await api.anmelden(email.trim(), passwort);
      setPasswort('');
      neuLaden();
    } catch (fehlschlag) {
      setFehler(
        fehlschlag instanceof Error
          ? fehlschlag.message
          : 'Anmeldung fehlgeschlagen',
      );
      setLaeuft(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        padding: 20,
        background: 'var(--td-bg)',
      }}
    >
      <div style={{ width: '100%', maxWidth: 380 }}>
        <div style={{ marginBottom: 26 }}>
          <div
            className="td-display"
            style={{ fontSize: 26, letterSpacing: '-0.02em' }}
          >
            TradeDiary
          </div>
          <div style={{ fontSize: 12, color: 'var(--td-neutral)', marginTop: 2 }}>
            Handelsjournal
          </div>
        </div>

        <form
          onSubmit={absenden}
          style={{
            background: 'var(--td-surface)',
            padding: '20px 20px 22px',
            borderTop: '3px solid var(--td-accent)',
          }}
        >
          <label
            className="td-label"
            htmlFor="td-email"
            style={{ display: 'block', marginBottom: 4 }}
          >
            E-Mail
          </label>
          <input
            id="td-email"
            type="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={feldStil}
          />

          <label
            className="td-label"
            htmlFor="td-passwort"
            style={{ display: 'block', margin: '14px 0 4px' }}
          >
            Passwort
          </label>
          <input
            id="td-passwort"
            type="password"
            // Damit der Schlüsselbund auf Mac und iPhone es anbietet und
            // speichert — sonst tippt man es auf dem Telefon jedes Mal.
            autoComplete="current-password"
            required
            value={passwort}
            onChange={(e) => setPasswort(e.target.value)}
            style={feldStil}
          />

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
                background: 'var(--td-neg-tint)',
              }}
            >
              ⚠ {fehler}
            </div>
          )}

          <button
            type="submit"
            disabled={laeuft}
            style={{
              width: '100%',
              marginTop: 18,
              padding: '11px 14px',
              background: laeuft ? 'transparent' : 'var(--td-accent)',
              color: laeuft ? 'var(--td-neutral)' : 'var(--td-on-accent)',
              border: '1px solid var(--td-line)',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            {laeuft ? 'Anmelden …' : 'Anmelden'}
          </button>
        </form>

        <p
          style={{
            fontSize: 11,
            color: 'var(--td-neutral)',
            lineHeight: 1.6,
            marginTop: 14,
          }}
        >
          Kein Konto anlegen und kein Passwort zurücksetzen im Browser — beides
          läuft am Rechner:
          <br />
          <code style={{ fontSize: 10 }}>python scripts/nutzer.py anlegen …</code>
        </p>
      </div>
    </div>
  );
}

const feldStil: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  background: 'var(--td-bg)',
  border: '1px solid var(--td-line)',
  color: 'var(--td-text)',
  font: 'inherit',
  fontSize: 14,
};
