'use client';

/**
 * Der geteilte Zustand: Filter, Einheit, Konto, Erscheinungsbild.
 *
 * Die Filterleiste gilt **global**. Zeitraum, Konto, Symbol und Seite
 * werden einmal oben gesetzt und wirken auf Dashboard, Kalender, Liste
 * und Reports gleichermaßen — man stellt seinen Ausschnitt einmal ein
 * und wandert dann durch die Auswertungen, statt jede Ansicht neu zu
 * konfigurieren.
 *
 * Dasselbe gilt für den Einheiten-Umschalter: Er rechnet jede Zahl auf
 * dem Screen aus derselben Quelle um. Deshalb liegt er hier und nicht
 * in einer einzelnen Ansicht.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { Account, Filters } from '../lib/api';
import { api } from '../lib/api';
import type { Unit } from '../lib/format';

type Theme = 'light' | 'dark';

interface Zustand {
  accounts: Account[];
  account: Account | null;
  accountId: number | null;
  setAccountId: (id: number | null) => void;

  filters: Filters;
  setFilters: (f: Partial<Filters>) => void;
  resetFilters: () => void;
  filterAktiv: boolean;

  unit: Unit;
  setUnit: (u: Unit) => void;

  theme: Theme;
  toggleTheme: () => void;

  laden: boolean;
  fehler: string | null;
}

const Kontext = createContext<Zustand | null>(null);

const LEER: Filters = {
  von: null,
  bis: null,
  symbol: null,
  direction: null,
};

export function AppState({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [filters, setFiltersRoh] = useState<Filters>(LEER);
  const [unit, setUnit] = useState<Unit>('eur');
  const [theme, setTheme] = useState<Theme>('light');
  const [laden, setLaden] = useState(true);
  const [fehler, setFehler] = useState<string | null>(null);

  useEffect(() => {
    let abgebrochen = false;
    api
      .accounts()
      .then((liste) => {
        if (abgebrochen) return;
        setAccounts(liste);
        // Standardmäßig das erste aktive Konto — ein verlorenes Konto
        // als Startansicht wäre eine merkwürdige Begrüßung.
        const aktiv = liste.find((a) => a.status === 'aktiv') ?? liste[0];
        setAccountId(aktiv?.id ?? null);
      })
      .catch((e) => !abgebrochen && setFehler(String(e.message ?? e)))
      .finally(() => !abgebrochen && setLaden(false));
    return () => {
      abgebrochen = true;
    };
  }, []);

  useEffect(() => {
    const gespeichert =
      typeof window !== 'undefined'
        ? (window.localStorage.getItem('td-theme') as Theme | null)
        : null;
    const system =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
    const gewaehlt = gespeichert ?? system;
    setTheme(gewaehlt);
    document.documentElement.setAttribute('data-theme', gewaehlt);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((alt) => {
      const neu = alt === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', neu);
      try {
        window.localStorage.setItem('td-theme', neu);
      } catch {
        /* Privater Modus — dann eben nur für diese Sitzung. */
      }
      return neu;
    });
  }, []);

  const setFilters = useCallback((teil: Partial<Filters>) => {
    setFiltersRoh((alt) => ({ ...alt, ...teil }));
  }, []);

  const resetFilters = useCallback(() => setFiltersRoh(LEER), []);

  const wert = useMemo<Zustand>(() => {
    const konto = accounts.find((a) => a.id === accountId) ?? null;
    return {
      accounts,
      account: konto,
      accountId,
      setAccountId,
      filters: { ...filters, account_id: accountId },
      setFilters,
      resetFilters,
      filterAktiv: Boolean(
        filters.von || filters.bis || filters.symbol || filters.direction,
      ),
      unit,
      setUnit,
      theme,
      toggleTheme,
      laden,
      fehler,
    };
  }, [
    accounts, accountId, filters, setFilters, resetFilters,
    unit, theme, toggleTheme, laden, fehler,
  ]);

  return <Kontext.Provider value={wert}>{children}</Kontext.Provider>;
}

export function useApp(): Zustand {
  const wert = useContext(Kontext);
  if (!wert) throw new Error('useApp muss innerhalb von <AppState> stehen');
  return wert;
}

/**
 * Lädt Daten und führt die drei Zustände sauber: lädt, Fehler, da.
 *
 * Wichtig ist der Fehlerfall. Ein fehlgeschlagener Abruf darf nicht wie
 * "keine Daten" aussehen — genau diese Verwechslung ist im Journal die
 * gefährlichste, weil ein stiller Ausfall dann wie ein ruhiger
 * Handelstag wirkt.
 */
export function useDaten<T>(
  laden: () => Promise<T>,
  deps: unknown[],
): { daten: T | null; laedt: boolean; fehler: string | null } {
  const [daten, setDaten] = useState<T | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<string | null>(null);

  useEffect(() => {
    let abgebrochen = false;
    setLaedt(true);
    setFehler(null);
    laden()
      .then((d) => !abgebrochen && setDaten(d))
      .catch((e) => !abgebrochen && setFehler(String(e.message ?? e)))
      .finally(() => !abgebrochen && setLaedt(false));
    return () => {
      abgebrochen = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { daten, laedt, fehler };
}
