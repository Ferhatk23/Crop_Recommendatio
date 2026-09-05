/**
 * Prüft den Nachbearbeitungs-Filter im echten Browser.
 *
 * Ein Journal führt man abends. Danach muss man wiederfinden, was noch
 * aussteht — sonst scrollt man durch dreihundert Zeilen und rät. Daran
 * stirbt die Gewohnheit: nicht am Aufschreiben, sondern am Suchen, wo man
 * stehen geblieben ist.
 *
 * Die API-Tests sagen, dass die Abfrage richtig filtert. Sie sagen nicht,
 * ob die Auswahlliste sie überhaupt erreicht, ob der Hinweis erscheint und
 * ob er verschwindet, sobald man den Trade angefasst hat. Genau das steht
 * hier.
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-nacharbeit.mjs
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
  viewport: { width: 1280, height: 1100 },
});
const page = await ctx.newPage();
page.on('pageerror', (e) => fehler.push(`Ausnahme: ${e.message}`));
const ERWARTET = /status of 401/;
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

/** Die Zahl in der Ergebniszeile — „N Trades · …". */
const anzahl = async () => {
  const text = await page.getByText(/Trades · /).first().innerText();
  return Number(text.match(/^([\d.]+)/)?.[1].replace(/\./g, '') ?? '0');
};

/* ------------------------------------------------------------------ */

console.log('\nDer Filter ist da und wirkt');
await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
await page.waitForTimeout(1800);

const auswahl = page.getByLabel('Nachbearbeitung');
pruefe((await auswahl.count()) > 0, 'die Auswahlliste steht auf der Seite');

const alle = await anzahl();
pruefe(alle > 0, `ungefiltert stehen ${alle} Trades da`);

await auswahl.selectOption('ohne_playbook');
await page.waitForTimeout(1800);
const ohnePlaybook = await anzahl();
pruefe(
  ohnePlaybook > 0 && ohnePlaybook < alle,
  `„ohne Playbook" schränkt ein (${ohnePlaybook} von ${alle})`,
);

await auswahl.selectOption('unberuehrt');
await page.waitForTimeout(1800);
const unberuehrt = await anzahl();
pruefe(
  unberuehrt <= ohnePlaybook,
  `„noch nicht angesehen" ist enger als „ohne Playbook" (${unberuehrt} ≤ ${ohnePlaybook})`,
);

/* ------------------------------------------------------------------ */

console.log('\nDie Zahl zählt die gefilterten, nicht alle');

// Der wahrscheinlichste stille Fehler: `total` zählt ungefiltert weiter.
// Dann stünde dauerhaft die Gesamtmenge da, und die Anzeige wäre
// schlimmer als keine — sie sähe nach Arbeit aus, die es nicht gibt.
pruefe(
  unberuehrt !== alle,
  'die Gesamtzahl folgt dem Filter statt stehenzubleiben',
);

// Und die Liste selbst darf nicht mehr Zeilen zeigen als die Zahl sagt.
const zeilen = await page.locator('tbody tr').count();
pruefe(
  zeilen <= unberuehrt,
  `die Liste zeigt nicht mehr Zeilen als gezählt (${zeilen} ≤ ${unberuehrt})`,
);

/* ------------------------------------------------------------------ */

console.log('\nDer Hinweis führt hin und verschwindet wieder');

await auswahl.selectOption('');
await page.waitForTimeout(1800);
const hinweis = page.getByRole('button', { name: /noch nicht angesehen/ });
pruefe((await hinweis.count()) > 0, 'der Hinweis steht da, auch ohne Filter');

await hinweis.first().click();
await page.waitForTimeout(1800);
pruefe(
  (await auswahl.inputValue()) === 'unberuehrt',
  'ein Klick darauf setzt den Filter',
);
pruefe(
  (await page.getByRole('button', { name: /noch nicht angesehen/ }).count()) === 0,
  'und der Hinweis tritt zurück, sobald man ihm gefolgt ist',
);

/* ------------------------------------------------------------------ */

console.log('\nEin bearbeiteter Trade fällt heraus');

// Die eigentliche Probe: Der Filter muss nachgeben, wenn man tut, wozu er
// auffordert. Täte er es nicht, bliebe die Liste ewig gleich lang und man
// hörte nach zwei Abenden auf.
const vorher = await anzahl();
const ziel = await page.locator('tbody tr a[href^="/trades/"]').first().getAttribute('href');
await page.goto(BASIS + ziel, { waitUntil: 'networkidle' });
await page.waitForTimeout(1800);

await page.getByLabel('Notiz').fill('Beim Prüflauf angesehen.');
await page.getByRole('button', { name: 'Speichern' }).first().click();
await page.waitForTimeout(1800);

await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
await page.getByLabel('Nachbearbeitung').selectOption('unberuehrt');
await page.waitForTimeout(1800);
const nachher = await anzahl();
pruefe(
  nachher === vorher - 1,
  `eine Notiz nimmt den Trade von der Liste (${vorher} -> ${nachher})`,
);

// Aufräumen: Die Notiz wieder entfernen, damit der nächste Lauf
// denselben Ausgangsstand vorfindet.
await page.goto(BASIS + ziel, { waitUntil: 'networkidle' });
await page.waitForTimeout(1800);
await page.getByLabel('Notiz').fill('');
await page.getByRole('button', { name: 'Speichern' }).first().click();
await page.waitForTimeout(1800);

await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
await page.getByLabel('Nachbearbeitung').selectOption('unberuehrt');
await page.waitForTimeout(1800);
pruefe((await anzahl()) === vorher, 'und der Ausgangsstand ist wiederhergestellt');

await browser.close();

console.log('');
if (fehler.length === 0) {
  console.log('Alles in Ordnung.');
  process.exit(0);
}
console.log(`${fehler.length} Beanstandung(en):`);
for (const f of [...new Set(fehler)]) console.log('  - ' + f);
process.exit(1);
