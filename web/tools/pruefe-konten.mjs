/**
 * Prüft die Kontoverwaltung im echten Browser.
 *
 * Diese Seite schliesst eine Lücke, die vorher die ganze App unbenutzbar
 * machte: Nach einer frischen Installation gab es einen Nutzer und ein
 * leeres Schema -- und keinen Weg zum eigenen Handelskonto ausser von
 * Hand per SQL.
 *
 * Der Schwerpunkt liegt deshalb auf zwei Fragen:
 *
 *   1. Kommt man vom leeren Zustand zu einem benutzbaren Konto?
 *   2. Wirken die eingetragenen Grenzwerte wirklich auf die Regel-Puffer?
 *      Eine Eingabe, die nirgends ankommt, ist schlimmer als keine --
 *      man verlässt sich dann auf einen Puffer, den es nicht gibt.
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-konten.mjs
 */

import process from 'node:process';

const BASIS = process.env.TD_WEB_URL ?? 'http://127.0.0.1:3000';
const CHROME = process.env.TD_CHROME ?? null;
const TLS_EGAL = process.env.TD_TLS_EGAL === '1';
const EMAIL = process.env.TD_EMAIL;
const PASSWORT = process.env.TD_PASSWORT;

if (!EMAIL || !PASSWORT) {
  console.error('TD_EMAIL und TD_PASSWORT setzen.');
  process.exit(2);
}

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  console.error('Playwright fehlt: npm install --no-save playwright');
  process.exit(2);
}

const fehler = [];
const pruefe = (bedingung, text) => {
  console.log(`  ${bedingung ? 'ok  ' : 'FEHL'}  ${text}`);
  if (!bedingung) fehler.push(text);
};

const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const ctx = await browser.newContext({
  ignoreHTTPSErrors: TLS_EGAL,
  viewport: { width: 1280, height: 1000 },
});
const page = await ctx.newPage();
page.on('pageerror', (e) => fehler.push(`Ausnahme: ${e.message}`));
// Zwei HTTP-Fehler gehoeren hier zum Ablauf und sind keine Defekte:
//   401 -- die Seite fragt vor der Anmeldung, wer da ist. Die Antwort
//          "niemand" ist der Grund, warum das Anmeldeformular erscheint.
//   400 -- die absichtlich falschen Eingaben weiter unten. Wuerden sie
//          *nicht* abgelehnt, waere genau das der Fehler.
// Alles andere zaehlt.
const ERWARTET = /status of (401|400)/;
page.on('console', (m) => {
  if (m.type() === 'error' && !ERWARTET.test(m.text())) {
    fehler.push(`Konsole: ${m.text()}`);
  }
});

await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.getByLabel('E-Mail').fill(EMAIL);
await page.getByLabel('Passwort').fill(PASSWORT);
await page.getByRole('button', { name: 'Anmelden' }).click();
await page.waitForTimeout(2200);

/* ------------------------------------------------------------------ */

console.log('\nZugang zur Seite');
await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.waitForTimeout(900);
const link = page.getByRole('link', { name: /Einstellungen/ });
pruefe((await link.count()) > 0, 'Verweis in der Seitenleiste');
await link.first().click();
await page.waitForTimeout(1400);
pruefe(page.url().includes('/einstellungen'), 'Seite öffnet sich');

/* ------------------------------------------------------------------ */

console.log('\nKonto anlegen');
const name = `Prüfkonto ${Date.now()}`;
await page.getByRole('button', { name: 'Konto hinzufügen' }).click();
await page.waitForTimeout(400);

await page.getByLabel('Bezeichnung').fill(name);
await page.getByLabel('Broker').fill('Alpha Capital');
await page.getByLabel('Startkapital').fill('50000');
await page.getByLabel('Tagesverlust').fill('2500');
await page.getByLabel('Gesamtverlust').fill('5000');
await page.getByLabel('Konsistenzregel').fill('0,4');

await page.getByRole('button', { name: 'Konto anlegen' }).click();
await page.waitForTimeout(2000);

pruefe((await page.getByText(name).count()) > 0, 'das Konto steht in der Liste');
pruefe(
  (await page.getByText('noch keine Daten').count()) > 0,
  'ein frisches Konto ist als leer erkennbar',
);

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1400);
pruefe((await page.getByText(name).count()) > 0, 'überlebt das Neuladen');

/* ------------------------------------------------------------------ */

console.log('\nFehleingaben werden abgefangen');

// Der wahrscheinlichste Eingabefehler: 40 statt 0,4.
await page.getByRole('button', { name: 'Konto hinzufügen' }).click();
await page.waitForTimeout(400);
await page.getByLabel('Bezeichnung').fill('Falsche Konsistenz');
await page.getByLabel('Konsistenzregel').fill('40');
await page.getByRole('button', { name: 'Konto anlegen' }).click();
await page.waitForTimeout(1400);

// `.first()` ist noetig: Next.js haelt einen eigenen role="alert" fuer
// die Routenansage bereit, der immer im Dokument steht.
const meldung = page.getByRole('alert').first();
pruefe((await meldung.count()) > 0, '40 statt 0,4 wird gemeldet');
const text = await meldung.innerText();
pruefe(text.includes('0,4'), 'die Meldung sagt, wie es richtig geht');
pruefe(
  text.includes('Konsistenzregel') && !text.includes('consistency_limit'),
  'sie nennt das Feld so, wie es auf dem Bildschirm heisst',
);

// Und ein Tageslimit über dem Gesamtverlust.
await page.getByLabel('Konsistenzregel').fill('0,4');
await page.getByLabel('Tagesverlust').fill('10000');
await page.getByLabel('Gesamtverlust').fill('5000');
await page.getByRole('button', { name: 'Konto anlegen' }).click();
await page.waitForTimeout(1400);
pruefe(
  (await page.getByRole('alert').first().count()) > 0,
  'Tagesverlust über Gesamtverlust wird gemeldet',
);

await page.getByRole('button', { name: 'Abbrechen' }).click();
await page.waitForTimeout(600);

/* ------------------------------------------------------------------ */

console.log('\nDie Grenzwerte wirken auf den Puffer');

// Das ist die eigentliche Probe: Eine Eingabe, die nirgends ankommt,
// wäre schlimmer als keine.
//
// Gezielt der *Gesamtverlust*-Puffer, nicht der erste beste: Auf dem
// Dashboard stehen drei nebeneinander, und der Tagesverlust aendert sich
// hier gar nicht. Wer den vergleicht, misst die falsche Kachel.
const pufferText = async () => {
  const alle = await page.getByText(/von .* verbraucht/).allInnerTexts();
  // Die Kacheln stehen in der Reihenfolge Tag, Gesamt, Konsistenz.
  return alle[1] ?? '';
};

await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
const vorher = await pufferText();

await page.goto(BASIS + '/einstellungen', { waitUntil: 'networkidle' });
await page.waitForTimeout(1400);
await page.getByRole('button', { name: 'bearbeiten' }).first().click();
await page.waitForTimeout(500);
await page.getByLabel('Gesamtverlust').first().fill('7500');
await page.getByRole('button', { name: 'Speichern' }).first().click();
await page.waitForTimeout(2000);

await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
const nachher = await pufferText();

pruefe(
  vorher !== nachher,
  `der geänderte Grenzwert schlägt auf das Dashboard durch (${vorher.replace(/\n/g, ' ')} -> ${nachher.replace(/\n/g, ' ')})`,
);
pruefe(
  (await page.getByText(/7\.500,00/).count()) > 0,
  'der neue Wert steht im Puffer',
);

/* ------------------------------------------------------------------ */

console.log('\nLöschen');
await page.goto(BASIS + '/einstellungen', { waitUntil: 'networkidle' });
await page.waitForTimeout(1400);

// Das Konto mit Trades darf nicht löschbar sein -- an ihm hängt
// Handelshistorie, die nirgends sonst steht.
const zeilen = page.locator('button', { hasText: 'bearbeiten' });
await zeilen.first().click();
await page.waitForTimeout(500);
pruefe(
  (await page.getByRole('button', { name: /leere Konto löschen/ }).count()) === 0,
  'ein Konto mit Trades bietet kein Löschen an',
);
await page.getByRole('button', { name: 'Abbrechen' }).first().click();
await page.waitForTimeout(400);

// Das frische, leere Konto dagegen schon.
const anzahlVorher = await page.getByText(/Prüfkonto/).count();
const pruefzeile = page
  .locator('div', { hasText: name })
  .locator('button', { hasText: 'bearbeiten' });
await pruefzeile.last().click();
await page.waitForTimeout(500);
const loeschen = page.getByRole('button', { name: /leere Konto löschen/ });
pruefe((await loeschen.count()) > 0, 'ein leeres Konto lässt sich löschen');

if (await loeschen.count()) {
  await loeschen.first().click();
  await page.waitForTimeout(1800);
  pruefe(
    (await page.getByText(/Prüfkonto/).count()) < anzahlVorher,
    'es ist danach weg',
  );
}

await browser.close();

console.log('');
if (fehler.length === 0) {
  console.log('Alles in Ordnung.');
  process.exit(0);
}
console.log(`${fehler.length} Beanstandung(en):`);
for (const f of [...new Set(fehler)]) console.log('  - ' + f);
process.exit(1);
