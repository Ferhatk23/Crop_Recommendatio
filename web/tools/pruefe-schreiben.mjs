/**
 * Prüft die Schreibfunktionen im echten Browser.
 *
 * Ein Test gegen die API sagt, dass der Endpunkt speichert. Er sagt
 * nicht, ob die Schaltfläche den Endpunkt trifft, ob die Anzeige den
 * Erfolg meldet und ob der Wert nach einem Neuladen noch da ist. Genau
 * dazwischen liegen die Fehler, die man erst im Betrieb merkt -- und bei
 * einer Notiz merkt man sie zu spät, weil es sie nur einmal gibt.
 *
 * Geprüft wird jeweils die ganze Kette: tippen, speichern, Seite neu
 * laden, wiederfinden.
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-schreiben.mjs
 *
 * Voraussetzung: Oberfläche und API laufen.
 */

import process from 'node:process';

const BASIS = process.env.TD_WEB_URL ?? 'http://127.0.0.1:3000';
const CHROME = process.env.TD_CHROME ?? null;

/**
 * Zertifikatsfehler übergehen -- nur zum Prüfen gegen einen Proxy mit
 * selbstsigniertem Zertifikat (`tls internal` bei Caddy). Im Betrieb
 * bleibt das aus: Ein Prüfskript, das TLS-Fehler grundsätzlich
 * verschluckt, würde ein abgelaufenes Zertifikat nicht mehr melden.
 */
const TLS_EGAL = process.env.TD_TLS_EGAL === '1';

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

const EMAIL = process.env.TD_EMAIL;
const PASSWORT = process.env.TD_PASSWORT;
if (!EMAIL || !PASSWORT) {
  console.error(
    'TD_EMAIL und TD_PASSWORT setzen (aus der Ausgabe von scripts/seed_db.py).',
  );
  process.exit(2);
}

const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
const ctx = await browser.newContext({
      ignoreHTTPSErrors: TLS_EGAL, viewport: { width: 1280, height: 1000 } });
const page = await ctx.newPage();

// Ohne Anmeldung zeigt jede Seite nur das Anmeldeformular.
await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.getByLabel('E-Mail').fill(EMAIL);
await page.getByLabel('Passwort').fill(PASSWORT);
await page.getByRole('button', { name: 'Anmelden' }).click();
await page.waitForTimeout(2000);
if (await page.getByLabel('Passwort').count()) {
  console.error('Anmeldung fehlgeschlagen -- stimmen TD_EMAIL und TD_PASSWORT?');
  await browser.close();
  process.exit(2);
}
page.on('pageerror', (e) => fehler.push(`Ausnahme: ${e.message}`));
page.on('console', (m) => {
  if (m.type() === 'error') fehler.push(`Konsole: ${m.text()}`);
});

/* ------------------------------------------------------------------ */
/* Notiz am Trade                                                      */
/* ------------------------------------------------------------------ */

console.log('\nNotiz am Trade');
await page.goto(`${BASIS}/trades`, { waitUntil: 'networkidle' });
const href = await page
  .locator('a[href^="/trades/"]')
  .first()
  .getAttribute('href');
await page.goto(BASIS + href, { waitUntil: 'networkidle' });
await page.waitForTimeout(700);

const marke = `Prüflauf ${Date.now()}`;
const notiz = page.getByLabel('Notiz', { exact: true });
await notiz.fill(marke);

pruefe(
  (await page.getByText('nicht gespeichert').count()) > 0,
  'ungesicherte Änderung wird angezeigt',
);

await page.getByRole('button', { name: 'Speichern' }).click();
await page.waitForTimeout(900);

pruefe(
  (await page.getByText('gespeichert', { exact: true }).count()) > 0,
  'Erfolg wird gemeldet',
);

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
pruefe(
  (await page.getByLabel('Notiz', { exact: true }).inputValue()) === marke,
  'Notiz überlebt das Neuladen',
);

// Wieder leeren, damit der Prüflauf nichts hinterlässt.
await page.getByLabel('Notiz', { exact: true }).fill('');
await page.getByRole('button', { name: 'Speichern' }).click();
await page.waitForTimeout(700);

/* ------------------------------------------------------------------ */
/* Tags                                                                */
/* ------------------------------------------------------------------ */

console.log('\nTags am Trade');
const tagName = `Prüf-${Date.now()}`;

// Gezählt wird die Entfernen-Schaltfläche, nicht der Text: Den Text
// trägt nach dem Anlegen auch der Vorschlag unter "Schon vergeben", und
// der bleibt zu Recht stehen, wenn man den Tag vom Trade nimmt. Wer auf
// den Text prüft, prüft die falsche Stelle -- und hält ein richtiges
// Verhalten für einen Fehler.
const vergeben = () =>
  page.getByRole('button', { name: `${tagName} entfernen` }).count();

await page.getByLabel('Neuer Tag').fill(tagName);
await page.getByRole('button', { name: 'Hinzufügen' }).click();
await page.waitForTimeout(900);

pruefe((await vergeben()) === 1, 'Tag erscheint');

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
pruefe((await vergeben()) === 1, 'Tag überlebt das Neuladen');

// Doppelt hinzufügen darf keinen zweiten anlegen.
await page.getByLabel('Neuer Tag').fill(tagName);
await page.getByRole('button', { name: 'Hinzufügen' }).click();
await page.waitForTimeout(800);
pruefe((await vergeben()) === 1, 'derselbe Tag wird nicht doppelt angelegt');

await page.getByRole('button', { name: `${tagName} entfernen` }).click();
await page.waitForTimeout(1000);
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
pruefe((await vergeben()) === 0, 'Entfernen wirkt und bleibt');

/* ------------------------------------------------------------------ */
/* Tagesjournal                                                        */
/* ------------------------------------------------------------------ */

console.log('\nTagesjournal');
await page.goto(`${BASIS}/journal`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1000);

const tagesfeld = page.locator('textarea').first();
const tagesmarke = `Tagesprüfung ${Date.now()}`;
await tagesfeld.fill(tagesmarke);
const [notizAntwort] = await Promise.all([
  page.waitForResponse(
    (r) => r.request().method() === 'PUT' && r.url().includes('/api/journal/'),
  ),
  page.getByRole('button', { name: 'Speichern' }).click(),
]);
pruefe(notizAntwort.ok(), 'Tagesnotiz wird angenommen');

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1100);
pruefe(
  (await page.locator('textarea').first().inputValue()) === tagesmarke,
  'Tagesnotiz überlebt das Neuladen',
);

// Die Stimmung ist ein Umschalter: Ein zweiter Klick auf dieselbe Stufe
// nimmt sie zurück. Der Test darf deshalb nicht annehmen, dass sie
// ungesetzt beginnt -- sonst schaltet er sie ab und hält das für einen
// verlorenen Wert. (Genau so ist es hier zuerst passiert.)
const stufe = () => page.getByRole('button', { name: 'Stimmung gut' });
const istGesetzt = async () =>
  (await stufe().getAttribute('aria-pressed')) === 'true';

// Auf die Antwort warten statt auf eine Zahl zu hoffen: Ein Neuladen,
// das die Anfrage noch abbricht, sähe wie ein verlorener Wert aus.
const klickeStufe = () =>
  Promise.all([
    page.waitForResponse(
      (r) => r.request().method() === 'PUT' && r.url().includes('/api/journal/'),
    ),
    stufe().click(),
  ]);

if (await istGesetzt()) await klickeStufe(); // erst auf einen bekannten Stand

const [stimmungsAntwort] = await klickeStufe();
pruefe(stimmungsAntwort.ok(), 'Stimmung wird angenommen');

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1100);
pruefe(await istGesetzt(), 'Stimmung überlebt das Neuladen');

// Und lässt sich wieder zurücknehmen.
await klickeStufe();
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1100);
pruefe(!(await istGesetzt()), 'Stimmung lässt sich zurücknehmen');

/* ------------------------------------------------------------------ */
/* Auswertung nach Tags                                                */
/* ------------------------------------------------------------------ */

console.log('\nAuswertung nach Setup');
await page.goto(`${BASIS}/reports`, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Setup' }).click();
await page.waitForTimeout(1200);

pruefe(
  (await page.getByText('ohne Setup').count()) > 0,
  'ungetaggte Trades stehen als eigene Gruppe da',
);
pruefe(
  (await page.getByText(/zählt dann in mehreren Gruppen/).count()) > 0,
  'die Überlappung wird erklärt',
);

await browser.close();

console.log('');
if (fehler.length === 0) {
  console.log('Alles in Ordnung.');
  process.exit(0);
}
console.log(`${fehler.length} Beanstandung(en):`);
for (const f of [...new Set(fehler)]) console.log('  - ' + f);
process.exit(1);
