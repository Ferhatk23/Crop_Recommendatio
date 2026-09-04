/**
 * Prüft Playbooks und die Regel-Häkchen im echten Browser.
 *
 * Der Schwerpunkt liegt auf den drei Stellen, an denen etwas still
 * schiefgehen kann und hinterher niemandem auffällt:
 *
 *   1. Kommt man vom leeren Zustand zu einem benutzbaren Playbook?
 *   2. Lassen sich die Regeln am Trade in **drei** Zuständen beantworten?
 *      Ein Kästchen mit zwei Zuständen könnte "nie angesehen" nicht von
 *      "alles gebrochen" unterscheiden.
 *   3. Kommen die Häkchen in der Auswertung an? Eine Eingabe, die
 *      nirgends ankommt, ist schlimmer als keine.
 *
 * Und die Gegenprobe, die am meisten wert ist: Verliert eine
 * Tippfehlerkorrektur an einer Regel die schon gesetzten Häkchen?
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-playbooks.mjs
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
// 401 gehört zum Ablauf: Die Seite fragt vor der Anmeldung, wer da ist,
// und die Antwort "niemand" ist der Grund für das Anmeldeformular.
// 409 ebenfalls: Die Rückfrage beim Streichen beantworteter Regeln wird
// weiter unten absichtlich ausgelöst.
const ERWARTET = /status of (401|409)/;
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
const link = page.getByRole('link', { name: /Playbooks/ });
pruefe((await link.count()) > 0, 'Verweis in der Seitenleiste');
await link.first().click();
await page.waitForTimeout(1400);
pruefe(page.url().includes('/playbooks'), 'Seite öffnet sich');

/* ------------------------------------------------------------------ */

console.log('\nPlaybook anlegen');
const name = `Prüfbuch ${Date.now()}`;
await page.getByRole('button', { name: 'Playbook hinzufügen' }).click();
await page.waitForTimeout(400);

await page.getByLabel('Name').fill(name);
await page.getByLabel('Beschreibung').fill('Nur zur Prüfung.');

// Erste Regel steht schon da, zwei weitere dazu.
const regelfelder = () => page.getByLabel('Regel', { exact: true });
await regelfelder().first().fill('Range markiert');
await page.getByRole('button', { name: '+ Regel hinzufügen' }).click();
await page.waitForTimeout(250);
await regelfelder().nth(1).fill('Stop hinter der Range');
await page.getByRole('button', { name: '+ Regel hinzufügen' }).click();
await page.waitForTimeout(250);
await regelfelder().nth(2).fill('Ruhig geblieben');
// Die dritte ist ein Merksatz: nichts zum Abhaken.
await page
  .getByLabel('am Trade abhakbar')
  .nth(2)
  .uncheck();

await page.getByRole('button', { name: 'Playbook anlegen' }).click();
await page.waitForTimeout(2000);

pruefe((await page.getByText(name).count()) > 0, 'das Playbook steht in der Liste');
pruefe(
  (await page.getByText(/3 Regeln, davon 2 abhakbar/).count()) > 0,
  'Merksatz und abhakbare Regel werden getrennt gezählt',
);

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1400);
pruefe((await page.getByText(name).count()) > 0, 'überlebt das Neuladen');

/* ------------------------------------------------------------------ */

console.log('\nDie Reihenfolge lässt sich ändern');
// Sie ist der Ablauf, nicht bloß Kosmetik: Ein Playbook wird von oben
// nach unten abgearbeitet.
const zeile = page.locator('div').filter({ hasText: name });
await zeile.locator('button', { hasText: 'bearbeiten' }).last().click();
await page.waitForTimeout(700);

const vorher = await regelfelder().first().inputValue();
await page.getByRole('button', { name: 'nach unten' }).first().click();
await page.waitForTimeout(300);
const nachher = await regelfelder().first().inputValue();
pruefe(vorher !== nachher, `die erste Regel wandert (${vorher} -> ${nachher})`);
await page.getByRole('button', { name: 'nach oben' }).nth(1).click();
await page.waitForTimeout(300);
pruefe(
  (await regelfelder().first().inputValue()) === vorher,
  'und wieder zurück',
);
await page.getByRole('button', { name: 'Abbrechen' }).first().click();
await page.waitForTimeout(500);

/* ------------------------------------------------------------------ */

console.log('\nRegeln am Trade beantworten');

await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
// Die Zeile selbst ist nicht anklickbar -- der Verweis sitzt in der Zelle.
await page.locator('tbody tr a[href^="/trades/"]').first().click();
await page.waitForTimeout(1800);
// Die Adresse merken: Weiter unten wird sie noch einmal gebraucht, und
// der Weg über die Verlaufstasten führt zwischendurch woanders hin.
const tradeUrl = page.url();
pruefe(/\/trades\/\d+/.test(page.url()), 'ein Trade lässt sich öffnen');

const auswahl = page.getByLabel('Playbook');
pruefe((await auswahl.count()) > 0, 'die Playbook-Auswahl ist da');
await auswahl.selectOption({ label: name });
await page.waitForTimeout(1800);

const ja = page.getByRole('button', { name: 'Range markiert: eingehalten' });
const nein = page.getByRole('button', { name: 'Stop hinter der Range: gebrochen' });
pruefe((await ja.count()) > 0, 'die Regeln des Playbooks erscheinen');
pruefe(
  (await page.getByText('Ruhig geblieben').count()) > 0,
  'der Merksatz steht daneben',
);
pruefe(
  (await page
    .getByRole('button', { name: 'Ruhig geblieben: eingehalten' })
    .count()) === 0,
  'der Merksatz hat kein Kästchen',
);

// Der dritte Zustand: Vor dem Klick ist nichts gedrückt.
pruefe(
  (await ja.getAttribute('aria-pressed')) === 'false' &&
    (await nein.getAttribute('aria-pressed')) === 'false',
  'unbeantwortet ist ein eigener Zustand, kein Nein',
);
pruefe((await page.getByText('offen').count()) >= 2, 'und er steht auch dran');

await ja.click();
await nein.click();
await page.waitForTimeout(300);
pruefe((await ja.getAttribute('aria-pressed')) === 'true', 'Ja lässt sich setzen');
pruefe(
  (await nein.getAttribute('aria-pressed')) === 'true',
  'Nein lässt sich setzen',
);

await page.getByRole('button', { name: 'Häkchen speichern' }).click();
await page.waitForTimeout(1800);
pruefe(
  (await page.getByText('gespeichert').count()) > 0,
  'der Speicherzustand ist sichtbar',
);

await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
pruefe(
  (await page
    .getByRole('button', { name: 'Range markiert: eingehalten' })
    .getAttribute('aria-pressed')) === 'true',
  'die Häkchen überleben das Neuladen',
);

// Zurück zum dritten Zustand -- ein zweiter Klick auf den gedrückten Knopf.
const jaNeu = page.getByRole('button', { name: 'Range markiert: eingehalten' });
await jaNeu.click();
await page.waitForTimeout(250);
pruefe(
  (await jaNeu.getAttribute('aria-pressed')) === 'false',
  'ein zweiter Klick führt zurück auf unbeantwortet',
);
await page.getByRole('button', { name: 'Verwerfen' }).first().click();
await page.waitForTimeout(400);
pruefe(
  (await jaNeu.getAttribute('aria-pressed')) === 'true',
  'Verwerfen stellt den gespeicherten Stand wieder her',
);

/* ------------------------------------------------------------------ */

console.log('\nEine Umformulierung verliert die Häkchen nicht');

// Der teuerste denkbare Fehler: Wer eine Regel umformuliert, dürfte
// niemals die Antworten von Dutzenden Trades verlieren. Der Verlust
// fiele nicht auf -- die Kästchen wären danach einfach leer.
await page.goto(BASIS + '/playbooks', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
const zeile2 = page.locator('div').filter({ hasText: name });
await zeile2.locator('button', { hasText: 'bearbeiten' }).last().click();
await page.waitForTimeout(700);
await regelfelder().first().fill('Asien-Range sauber markiert');
await page.getByRole('button', { name: 'Speichern' }).first().click();
await page.waitForTimeout(2000);

await page.goto(tradeUrl, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
const umbenannt = page.getByRole('button', {
  name: 'Asien-Range sauber markiert: eingehalten',
});
pruefe((await umbenannt.count()) > 0, 'die Regel trägt den neuen Text');
pruefe(
  (await umbenannt.getAttribute('aria-pressed')) === 'true',
  'und das Häkchen steht noch',
);

/* ------------------------------------------------------------------ */

console.log('\nDie Häkchen kommen in der Auswertung an');

await page.goto(BASIS + '/reports', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
await page.getByRole('button', { name: 'Regeltreue' }).click();
await page.waitForTimeout(2000);

pruefe(
  (await page.getByText(/Selbstberichtet/).count()) > 0,
  'die Auswertung sagt, dass sie selbstberichtet ist',
);
pruefe(
  (await page.getByText(/eingehalten/).count()) > 0 &&
    (await page.getByText(/gebrochen/).count()) > 0,
  'beide Gruppen stehen da',
);
pruefe(
  (await page.getByText(/nicht vollständig durchgegangen/).count()) > 0,
  'unbeantwortete Trades werden getrennt ausgewiesen',
);
pruefe(
  (await page.getByText('Netto wenn gebrochen').count()) > 0,
  'je Regel steht, was der Bruch gekostet hat',
);

/* ------------------------------------------------------------------ */

console.log('\nAufräumen');

// Solange der Trade daran hängt, darf das Playbook nicht weg -- die
// Zuordnung ist eine Aussage über einen vergangenen Trade.
await page.goto(BASIS + '/playbooks', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
const zeile3 = page.locator('div').filter({ hasText: name });
await zeile3.locator('button', { hasText: 'bearbeiten' }).last().click();
await page.waitForTimeout(700);
pruefe(
  (await page.getByRole('button', { name: /ungenutzte Playbook löschen/ }).count()) === 0,
  'ein Playbook mit Trades bietet kein Löschen an',
);

// Am Trade abwählen, dann geht es -- und die Prüfung hinterlässt nichts.
// Ohne das sammelten sich bei jedem Lauf ein Playbook und ein paar
// Häkchen mehr in der Datenbank an.
await page.goto(tradeUrl, { waitUntil: 'networkidle' });
await page.waitForTimeout(1800);
await page.getByLabel('Playbook').selectOption('');
await page.waitForTimeout(1800);

await page.goto(BASIS + '/playbooks', { waitUntil: 'networkidle' });
await page.waitForTimeout(1600);
const zeile4 = page.locator('div').filter({ hasText: name });
await zeile4.locator('button', { hasText: 'bearbeiten' }).last().click();
await page.waitForTimeout(700);
const loeschen = page.getByRole('button', { name: /ungenutzte Playbook löschen/ });
pruefe(
  (await loeschen.count()) > 0,
  'nach dem Abwählen lässt es sich löschen',
);
if (await loeschen.count()) {
  await loeschen.first().click();
  await page.waitForTimeout(1800);
  pruefe((await page.getByText(name).count()) === 0, 'es ist danach weg');
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
