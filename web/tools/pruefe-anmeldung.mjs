/**
 * Prüft die Anmeldung im echten Browser.
 *
 * Der Teil, den Server-Tests nicht erreichen: ob das Cookie zwischen
 * zwei Ursprüngen überhaupt ankommt. Die Oberfläche läuft auf Port 3000,
 * die API auf 8000 -- ohne `credentials: 'include'` schickt der Browser
 * das Sitzungs-Cookie nicht mit, und die App wäre dauerhaft abgemeldet,
 * obwohl die Anmeldung sauber geklappt hat. Ein Test gegen die API sieht
 * davon nichts.
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-anmeldung.mjs
 */

import process from 'node:process';

const BASIS = process.env.TD_WEB_URL ?? 'http://127.0.0.1:3000';
const CHROME = process.env.TD_CHROME ?? null;
const EMAIL = process.env.TD_EMAIL;
const PASSWORT = process.env.TD_PASSWORT;

if (!EMAIL || !PASSWORT) {
  console.error(
    'TD_EMAIL und TD_PASSWORT setzen (aus der Ausgabe von scripts/seed_db.py).',
  );
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
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => fehler.push(`Ausnahme: ${e.message}`));

/* --- Ohne Anmeldung ------------------------------------------------- */

console.log('\nOhne Anmeldung');
await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
await page.waitForTimeout(900);

pruefe(
  (await page.getByLabel('Passwort').count()) > 0,
  'geschützte Seite zeigt die Anmeldung',
);
pruefe(
  (await page.getByText(/Keine Verbindung zur API/).count()) === 0,
  'kein Fehlerbild — "nicht angemeldet" ist kein Defekt',
);
pruefe(
  !(await page.content()).includes('Netto-Ergebnis'),
  'keine Kennzahlen vor der Anmeldung',
);

/* --- Falsches Passwort ---------------------------------------------- */

console.log('\nFalsches Passwort');
await page.getByLabel('E-Mail').fill(EMAIL);
await page.getByLabel('Passwort').fill('falsch aber lang genug');
await page.getByRole('button', { name: 'Anmelden' }).click();
await page.waitForTimeout(1200);

pruefe(
  (await page.getByRole('alert').count()) > 0,
  'Fehlschlag wird gemeldet',
);
pruefe(
  (await page.getByLabel('Passwort').count()) > 0,
  'bleibt auf der Anmeldung',
);

/* --- Richtiges Passwort --------------------------------------------- */

console.log('\nAnmeldung');
await page.getByLabel('Passwort').fill(PASSWORT);
await page.getByRole('button', { name: 'Anmelden' }).click();
await page.waitForTimeout(2500);

pruefe(
  (await page.getByLabel('Passwort').count()) === 0,
  'Anmeldung verschwindet',
);
pruefe(
  (await page.locator('.td-tabelle, .td-karten').count()) > 0,
  'die Trades sind da',
);

// Das eigentliche Ziel dieses Skripts.
const kekse = await ctx.cookies();
const sitzung = kekse.find((k) => k.name === 'tradediary_sitzung');
pruefe(!!sitzung, 'Sitzungs-Cookie ist gesetzt');
pruefe(sitzung?.httpOnly === true, 'Cookie ist HttpOnly — JavaScript kommt nicht ran');

pruefe(
  await page.evaluate(() => !document.cookie.includes('tradediary_sitzung')),
  'document.cookie gibt die Marke nicht her',
);

/* --- Die Anmeldung hält --------------------------------------------- */

console.log('\nNach dem Neuladen');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1800);
pruefe(
  (await page.getByLabel('Passwort').count()) === 0,
  'bleibt angemeldet',
);

await page.goto(BASIS + '/reports', { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
pruefe(
  (await page.getByLabel('Passwort').count()) === 0,
  'auch auf einer anderen Seite',
);

/* --- Abmelden -------------------------------------------------------- */

console.log('\nAbmelden');
await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
const knopf = page.getByRole('button', { name: /Abmelden/ });
if ((await knopf.count()) === 0) {
  pruefe(false, 'Abmelden-Schaltfläche gefunden');
} else {
  await knopf.first().click();
  await page.waitForTimeout(1500);
  pruefe(
    (await page.getByLabel('Passwort').count()) > 0,
    'zurück auf der Anmeldung',
  );

  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  pruefe(
    (await page.getByLabel('Passwort').count()) > 0,
    'bleibt abgemeldet — die Sitzung ist auch serverseitig weg',
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
