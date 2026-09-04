'use client';

/**
 * Navigation und Filterleiste.
 *
 * Drei Breiten, drei Muster: Seitenleiste (1280), Symbolspalte (834),
 * Tab-Leiste unten (390). Die Tab-Leiste sitzt unten, weil dort der
 * Daumen ist — und über dem Home-Indikator, damit man beim Wechseln
 * nicht versehentlich nach Hause tippt.
 *
 * Der Herzschlag der Übernahme steht dauerhaft in der Navigation, nicht
 * in einer Meldung, die man wegklickt: Er ist die Statuszeile des
 * ganzen Produkts.
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Anmeldung } from './Anmeldung';
import { useApp } from './AppState';
import { SyncHeartbeat, TagChip } from './primitives';
import { UNITS } from '../lib/format';

const PUNKTE = [
  { href: '/', label: 'Dashboard', icon: '▨' },
  { href: '/kalender', label: 'Kalender', icon: '▦' },
  { href: '/trades', label: 'Trades', icon: '▤' },
  { href: '/journal', label: 'Journal', icon: '▥' },
  { href: '/reports', label: 'Reports', icon: '◪' },
];

function NavLinks({ symbole }: { symbole?: boolean }) {
  const pfad = usePathname();
  return (
    <nav style={{ display: 'flex', flexDirection: 'column' }}>
      {PUNKTE.map((p) => {
        const aktiv = p.href === '/' ? pfad === '/' : pfad.startsWith(p.href);
        return (
          <Link
            key={p.href}
            href={p.href}
            aria-current={aktiv ? 'page' : undefined}
            className="td-tap"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: symbole ? '0 0 0 20px' : '0 14px',
              background: aktiv ? 'var(--td-accent)' : 'transparent',
              color: aktiv ? 'var(--td-on-accent)' : 'var(--td-text)',
              fontWeight: aktiv ? 600 : 400,
            }}
            title={p.label}
          >
            <span aria-hidden style={{ fontSize: 15 }}>
              {p.icon}
            </span>
            {!symbole && <span>{p.label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

function KontoWahl() {
  const { accounts, accountId, setAccountId } = useApp();
  return (
    <div style={{ padding: '10px 14px' }}>
      <label className="td-label" htmlFor="konto">
        Konto
      </label>
      <select
        id="konto"
        value={accountId ?? ''}
        onChange={(e) => setAccountId(Number(e.target.value))}
        style={{ width: '100%', marginTop: 4, background: 'var(--td-bg)' }}
      >
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.label}
            {a.status !== 'aktiv' ? ` · ${a.status}` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

export function UnitSwitcher() {
  const { unit, setUnit } = useApp();
  return (
    <div
      role="group"
      aria-label="Einheit"
      style={{ display: 'flex', border: '1px solid var(--td-line)' }}
    >
      {UNITS.map((u) => {
        const aktiv = u.id === unit;
        return (
          <button
            key={u.id}
            onClick={() => setUnit(u.id)}
            aria-pressed={aktiv}
            style={{
              minWidth: 44,
              padding: '0 10px',
              background: aktiv ? 'var(--td-accent)' : 'transparent',
              color: aktiv ? 'var(--td-on-accent)' : 'var(--td-text)',
              fontWeight: aktiv ? 600 : 400,
              fontSize: 12,
              borderRight: '1px solid var(--td-line)',
            }}
          >
            {u.label}
          </button>
        );
      })}
    </div>
  );
}

export function FilterBar({ symbole = [] }: { symbole?: string[] }) {
  const { filters, setFilters, resetFilters, filterAktiv } = useApp();

  const chips: { label: string; clear: () => void }[] = [];
  if (filters.von) chips.push({ label: `ab ${filters.von}`, clear: () => setFilters({ von: null }) });
  if (filters.bis) chips.push({ label: `bis ${filters.bis}`, clear: () => setFilters({ bis: null }) });
  if (filters.symbol) chips.push({ label: filters.symbol, clear: () => setFilters({ symbol: null }) });
  if (filters.direction)
    chips.push({
      label: filters.direction === 'long' ? 'Long' : 'Short',
      clear: () => setFilters({ direction: null }),
    });

  return (
    <div
      style={{
        borderBottom: '2px solid var(--td-divider)',
        padding: '10px 0',
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        alignItems: 'center',
      }}
    >
      <input
        type="date"
        aria-label="Zeitraum von"
        value={filters.von ?? ''}
        onChange={(e) => setFilters({ von: e.target.value || null })}
        style={{ minWidth: 140 }}
      />
      <input
        type="date"
        aria-label="Zeitraum bis"
        value={filters.bis ?? ''}
        onChange={(e) => setFilters({ bis: e.target.value || null })}
        style={{ minWidth: 140 }}
      />
      <select
        aria-label="Symbol"
        value={filters.symbol ?? ''}
        onChange={(e) => setFilters({ symbol: e.target.value || null })}
      >
        <option value="">Alle Symbole</option>
        {symbole.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select
        aria-label="Seite"
        value={filters.direction ?? ''}
        onChange={(e) => setFilters({ direction: e.target.value || null })}
      >
        <option value="">Long und Short</option>
        <option value="long">nur Long</option>
        <option value="short">nur Short</option>
      </select>

      <div style={{ marginLeft: 'auto' }}>
        <UnitSwitcher />
      </div>

      {/* Aktive Filter als entfernbare Chips — sonst wundert man sich
          über einen leeren Screen und sucht den Fehler in den Daten. */}
      {filterAktiv && (
        <div
          style={{
            display: 'flex',
            gap: 6,
            flexWrap: 'wrap',
            alignItems: 'center',
            width: '100%',
          }}
        >
          {chips.map((c) => (
            <TagChip
              key={c.label}
              tag={{ label: c.label, kind: 'setup' }}
              onRemove={c.clear}
            />
          ))}
          <button
            onClick={resetFilters}
            style={{
              fontSize: 11,
              color: 'var(--td-neutral)',
              textDecoration: 'underline',
              minHeight: 32,
            }}
          >
            alle zurücksetzen
          </button>
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { account, theme, toggleTheme, laden, fehler, angemeldet, nutzer, abmelden } =
    useApp();
  const pfad = usePathname();

  // Solange unklar ist, wer da ist, wird nichts gezeigt. Ein kurzes
  // Aufblitzen der Anmeldeseite bei jedem Neuladen waere schlimmer als
  // ein Sekundenbruchteil Leere -- es saehe jedes Mal so aus, als waere
  // man rausgeflogen.
  if (laden) {
    return (
      <main style={{ padding: 24, color: 'var(--td-neutral)', fontSize: 12 }}>
        lädt …
      </main>
    );
  }

  if (!angemeldet) return <Anmeldung />;

  if (fehler) {
    return (
      <main style={{ padding: 24, maxWidth: 640 }}>
        <h1 className="td-display" style={{ fontSize: 26 }}>
          Keine Verbindung zur API
        </h1>
        <p style={{ color: 'var(--td-neutral)' }}>{fehler}</p>
        <p style={{ color: 'var(--td-neutral)', fontSize: 11 }}>
          Läuft der Server? <code>uvicorn tradediary.api.main:app --port 8000</code>
        </p>
      </main>
    );
  }

  return (
    <div className="td-shell">
      {/* Seitenleiste — ab 834 px sichtbar, ab 1280 mit Beschriftung */}
      <aside className="td-rail">
        <div style={{ padding: '16px 14px 10px' }}>
          <span className="td-display nur-breit-inline" style={{ fontSize: 17 }}>
            TradeDiary
          </span>
          <span className="nur-tablet-inline td-display" style={{ fontSize: 17 }}>
            TD
          </span>
        </div>

        <div className="nur-breit">
          <KontoWahl />
        </div>

        <hr className="td-line" />
        <NavLinks />
        <div className="nur-tablet">
          <NavLinks symbole />
        </div>

        <div style={{ marginTop: 'auto', padding: '0 14px 12px' }}>
          {account && (
            <div className="nur-breit">
              <SyncHeartbeat sync={account.sync} />
            </div>
          )}
          <button
            onClick={toggleTheme}
            className="td-tap"
            style={{
              width: '100%',
              fontSize: 11,
              color: 'var(--td-neutral)',
              borderTop: '1px solid var(--td-line)',
            }}
          >
            {theme === 'dark' ? '☀ Hell' : '☾ Dunkel'}
          </button>
          <button
            onClick={() => void abmelden()}
            className="td-tap nur-breit"
            title={nutzer?.email ?? undefined}
            style={{
              width: '100%',
              fontSize: 11,
              color: 'var(--td-neutral)',
              borderTop: '1px solid var(--td-line)',
              textAlign: 'left',
              paddingLeft: 0,
            }}
          >
            ⏻ Abmelden
          </button>
        </div>
      </aside>

      <main className="td-main">
        {laden ? (
          <div style={{ padding: 24, color: 'var(--td-neutral)' }}>lädt …</div>
        ) : (
          children
        )}
      </main>

      {/* Tab-Leiste — nur auf dem Telefon */}
      <nav className="td-tabbar" aria-label="Hauptnavigation">
        {PUNKTE.map((p) => {
          const aktiv = p.href === '/' ? pfad === '/' : pfad.startsWith(p.href);
          return (
            <Link
              key={p.href}
              href={p.href}
              aria-current={aktiv ? 'page' : undefined}
              style={{
                flex: 1,
                minHeight: 'var(--td-tap)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                fontSize: 9,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: aktiv ? 'var(--td-accent)' : 'var(--td-neutral)',
                fontWeight: aktiv ? 700 : 400,
                borderTop: aktiv
                  ? '2px solid var(--td-accent)'
                  : '2px solid transparent',
              }}
            >
              <span aria-hidden style={{ fontSize: 15 }}>
                {p.icon}
              </span>
              {p.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

/** Seitenkopf mit Titel und optionalem Zusatz. */
export function PageHead({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-end',
        gap: 16,
        flexWrap: 'wrap',
        paddingBottom: 12,
      }}
    >
      <div>
        <h1 className="td-display" style={{ fontSize: 26, margin: 0 }}>
          {title}
        </h1>
        {sub && (
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>{sub}</span>
        )}
      </div>
      {right}
    </div>
  );
}
