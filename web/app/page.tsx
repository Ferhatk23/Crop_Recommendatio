'use client';

/**
 * Dashboard — „Wie läuft es gerade?" in unter fünf Sekunden.
 *
 * Der Regel-Puffer steht ganz oben, noch vor den Kennzahlen. Für einen
 * Prop-Trader ist er die wichtigste Information im Produkt: Ein
 * gerissenes Tageslimit kostet das Konto, ein mittelmäßiger Profit
 * Factor kostet nur Zeit.
 */

import { useApp, useDaten } from '../components/AppState';
import { FilterBar, PageHead } from '../components/Shell';
import { EquityCurve, ScoreDisplay } from '../components/charts';
import { AccountLost, RuleBuffer } from '../components/RuleBuffer';
import { EmptyState, KpiTile } from '../components/primitives';
import { TradeList } from '../components/TradeList';
import { api } from '../lib/api';
import {
  faktor,
  geld,
  monatsname,
  prozent,
  rMultiple,
  zahl,
} from '../lib/format';

export default function Dashboard() {
  const { filters, accountId, account, unit } = useApp();

  const uebersicht = useDaten(
    () => api.overview(filters),
    [accountId, filters.von, filters.bis, filters.symbol, filters.direction],
  );
  const letzte = useDaten(
    () => api.trades({ ...filters, limit: 5 }),
    [accountId, filters.von, filters.bis, filters.symbol, filters.direction],
  );
  const symbole = useDaten(() => api.symbols(accountId), [accountId]);

  const jetzt = new Date();
  const zeitraumText = filters.von || filters.bis
    ? `${filters.von ?? 'Beginn'} bis ${filters.bis ?? 'heute'}`
    : `${monatsname(jetzt.getMonth() + 1)} ${jetzt.getFullYear()} · gesamter Zeitraum`;

  if (uebersicht.fehler) {
    return (
      <>
        <PageHead title="Dashboard" />
        <EmptyState
          cause="sync"
          detail={`Die Auswertung konnte nicht geladen werden: ${uebersicht.fehler}`}
        />
      </>
    );
  }

  if (uebersicht.laedt || !uebersicht.daten) {
    return (
      <>
        <PageHead title="Dashboard" />
        <div style={{ color: 'var(--td-neutral)', padding: '20px 0' }}>lädt …</div>
      </>
    );
  }

  const { metrics: m, score, rules, equity_curve } = uebersicht.daten;
  const waehrung = account?.currency === 'USD' ? '$' : '€';

  if (m.trade_count === 0) {
    return (
      <>
        <PageHead title="Dashboard" sub={zeitraumText} />
        <FilterBar symbole={symbole.daten ?? []} />
        <div style={{ marginTop: 16 }}>
          <EmptyState cause="filter" />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="Dashboard"
        sub={`${account?.label ?? 'Alle Konten'} · ${zeitraumText}`}
      />
      <FilterBar symbole={symbole.daten ?? []} />

      {/* Konto gerissen — kein Statuswert, sondern das Ende dieses Kontos. */}
      {rules.account_lost && account && (
        <div style={{ marginTop: 14 }}>
          <AccountLost
            buffer={
              rules.daily_loss.state === 'gerissen'
                ? rules.daily_loss
                : rules.max_loss
            }
            accountLabel={account.label}
          />
        </div>
      )}

      {/* Regel-Puffer — das Wichtigste, deshalb ganz oben. */}
      <section className="td-section" style={{ marginTop: 16, borderTop: 'none', paddingTop: 0 }}>
        <span className="td-label">Regel-Puffer</span>
        <div className="td-grid td-grid-3" style={{ marginTop: 6 }}>
          <RuleBuffer buffer={rules.daily_loss} />
          <RuleBuffer buffer={rules.max_loss} />
          <RuleBuffer buffer={rules.consistency} alsAnteil />
        </div>
      </section>

      {/* Kennzahlen */}
      <section className="td-section">
        <span className="td-label">Kennzahlen · {zeitraumText}</span>
        <div className="td-grid td-grid-kpi" style={{ marginTop: 6 }}>
          <KpiTile
            label="Netto-Ergebnis"
            value={geld(m.net_pnl, waehrung)}
            outcomeValue={m.net_pnl}
            period={zeitraumText}
            large
          />
          <KpiTile
            label="Trefferquote"
            value={prozent(m.win_rate)}
            outcomeValue={null}
            reason={m.win_rate === null ? 'nur Break-even-Trades' : undefined}
            compare={`${m.wins} G · ${m.losses} V · ${m.scratches} Scratch`}
            large
          />
          <KpiTile
            label="Profit Factor"
            value={faktor(m.profit_factor)}
            outcomeValue={null}
            reason={m.profit_factor === null ? 'kein Verlust im Zeitraum' : undefined}
            compare={`${geld(m.gross_profit)} / ${geld(-m.gross_loss)}`}
            large
          />
          <KpiTile
            label="Ø Gewinn / Verlust"
            value={faktor(m.win_loss_ratio)}
            outcomeValue={null}
            reason={m.win_loss_ratio === null ? 'kein Verlust im Zeitraum' : undefined}
            compare={`${geld(m.avg_win)} · ${geld(m.avg_loss ? -m.avg_loss : null)}`}
            large
          />
        </div>

        <div className="td-grid td-grid-4" style={{ marginTop: 2 }}>
          <KpiTile
            label="Max Drawdown"
            value={geld(-m.max_drawdown, waehrung)}
            outcomeValue={-m.max_drawdown}
            period="über die Trade-Reihenfolge"
          />
          <KpiTile
            label="Erwartung je Trade"
            value={geld(m.expectancy, waehrung)}
            outcomeValue={m.expectancy}
            compare={
              m.expectancy_r !== null
                ? `${rMultiple(m.expectancy_r)} in R`
                : `${zahl(m.trades_without_stop)} Trades ohne Stop`
            }
          />
          <KpiTile
            label="Handelstage"
            value={zahl(m.trading_days)}
            outcomeValue={null}
            compare={`${zahl(m.trade_count)} Trades`}
          />
          <KpiTile
            label="Längste Serie"
            value={`${zahl(m.max_consecutive_wins)} / ${zahl(m.max_consecutive_losses)}`}
            outcomeValue={null}
            compare="Gewinne / Verluste"
          />
        </div>
      </section>

      {/* Equity-Kurve */}
      <section className="td-section">
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
          }}
        >
          <span className="td-label">Equity-Verlauf</span>
          <span style={{ fontSize: 11, color: 'var(--td-neutral)' }}>
            Rückgänge vom Hoch grau hinterlegt
          </span>
        </div>
        <div className="td-card" style={{ marginTop: 6 }}>
          <EquityCurve points={equity_curve} currency={waehrung} />
        </div>
      </section>

      {/* Score */}
      <section className="td-section">
        <span className="td-label">Bewertung</span>
        <div className="td-card" style={{ marginTop: 6 }}>
          <ScoreDisplay
            total={score.total}
            parts={score.parts}
            missing={score.missing}
          />
        </div>
      </section>

      {/* Letzte Trades */}
      <section className="td-section">
        <span className="td-label">Zuletzt geschlossen</span>
        <div style={{ marginTop: 6 }}>
          {letzte.daten && letzte.daten.trades.length > 0 ? (
            <TradeList trades={letzte.daten.trades} />
          ) : (
            <EmptyState cause="filter" />
          )}
        </div>
      </section>
    </>
  );
}
