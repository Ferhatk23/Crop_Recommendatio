/**
 * Prüft die laufende Oberfläche im echten Browser.
 *
 * Unit-Tests sagen, dass `outcome()` das Richtige zurückgibt. Sie sagen
 * nicht, ob die Schrift geladen wurde, ob auf dem iPad überhaupt etwas
 * gerendert wird oder ob die Konsole voller Fehler steht. Genau dort lagen
 * die meisten Fehler dieses Projekts:
 *
 *   - CORS: die API erlaubte `localhost:3000`, der Browser kam als
 *     `127.0.0.1:3000` -- jede Seite blieb leer.
 *   - Die Trade-Liste hatte zwischen 720 und 1099 px eine tote Zone:
 *     Tabelle schon aus, Karten noch nicht an.
 *   - Die Schrift kam von Google Fonts und wurde blockiert.
 *
 * Alle drei sind hier als Zusicherung hinterlegt. Das Skript endet mit
 * Rückgabewert 1, wenn eine davon bricht -- damit ein Fehlschlag nicht
 * bloß in der Ausgabe steht, sondern auch auffällt.
 *
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-oberflaeche.mjs
 *   TD_EMAIL=… TD_PASSWORT=… node tools/pruefe-oberflaeche.mjs --bilder
 *
 * Voraussetzung: `npm run dev` läuft, und die API antwortet.
 *
 * Angemeldet wird einmal, dann teilen sich alle Kontexte den Zustand:
 * Seit es eine Anmeldung gibt, zeigt jede Seite ohne sie nur das
 * Anmeldeformular -- und geprüft würde dann fünfmal dasselbe Formular.
 */

import fs from 'node:fs';
import process from 'node:process';

const BASIS = process.env.TD_WEB_URL ?? 'http://127.0.0.1:3000';
const BILDER = process.argv.includes('--bilder');
// Nicht nach `/tmp`: Die Bilder zeigen den vollständigen Journalinhalt --
// Kontostände, Notizen, Symbole -- und lägen dort für jeden lesbar unter
// einem vorhersagbaren Namen. Hier neben dem Projekt, aus dem Git
// herausgehalten.
const BILDER_ZIEL = process.env.TD_SHOTS ?? '.td-shots';

/** Pfad zum vorinstallierten Chromium, falls Playwright seinen nicht findet. */
const CHROME = process.env.TD_CHROME ?? null;

/**
 * Zertifikatsfehler übergehen -- nur zum Prüfen gegen einen Proxy mit
 * selbstsigniertem Zertifikat (`tls internal` bei Caddy). Im Betrieb
 * bleibt das aus: Ein Prüfskript, das TLS-Fehler grundsätzlich
 * verschluckt, würde ein abgelaufenes Zertifikat nicht mehr melden.
 */
const TLS_EGAL = process.env.TD_TLS_EGAL === '1';

const SEITEN = [
  ['Dashboard', '/'],
  ['Kalender', '/kalender'],
  ['Trades', '/trades'],
  ['Reports', '/reports'],
  ['Journal', '/journal'],
];

/** Die drei Breiten aus dem Designsystem -- Telefon, Tablet, Schreibtisch. */
const BREITEN = [
  ['Telefon', 390, 844],
  ['Tablet', 834, 1112],
  ['Desktop', 1280, 900],
];

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  console.error(
    'Playwright fehlt. Für diese Prüfung: npm install --no-save playwright',
  );
  process.exit(2);
}

const fehler = [];
const melde = (wo, text) => fehler.push(`${wo}: ${text}`);

const EMAIL = process.env.TD_EMAIL;
const PASSWORT = process.env.TD_PASSWORT;
if (!EMAIL || !PASSWORT) {
  console.error(
    'TD_EMAIL und TD_PASSWORT setzen (aus der Ausgabe von scripts/seed_db.py).',
  );
  process.exit(2);
}

const browser = await chromium.launch(
  CHROME ? { executablePath: CHROME } : {},
);

/**
 * Meldet sich einmal an und gibt den Sitzungszustand zurück.
 *
 * Der wird an jeden weiteren Kontext gereicht -- sonst müsste sich jede
 * Breite und jedes Farbschema neu anmelden, und das kostet je 100 ms
 * Passwortprüfung plus einen Seitenwechsel.
 */
async function anmeldezustand() {
  const ctx = await browser.newContext({
      ignoreHTTPSErrors: TLS_EGAL, viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
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
  const zustand = await ctx.storageState();
  await ctx.close();
  return zustand;
}

const sitzung = await anmeldezustand();

/** Hängt die Fehler-Aufzeichnung an eine Seite. */
function beobachte(page, wo) {
  page.on('console', (m) => {
    if (m.type() === 'error') melde(wo, `Konsole: ${m.text()}`);
  });
  page.on('pageerror', (e) => melde(wo, `Ausnahme: ${e.message}`));
  page.on('requestfailed', (r) => {
    const url = r.url();
    // Abgebrochene Navigationen sind kein Defekt.
    if (r.failure()?.errorText === 'net::ERR_ABORTED') return;
    melde(wo, `Request fehlgeschlagen: ${r.failure()?.errorText} ${url}`);
  });
  page.on('response', (r) => {
    if (r.status() >= 400) melde(wo, `HTTP ${r.status()} ${r.url()}`);
  });
}

console.log(`Prüfe ${BASIS}\n`);

if (BILDER) fs.mkdirSync(BILDER_ZIEL, { recursive: true });

for (const [modus, theme] of [
  ['hell', 'light'],
  ['dunkel', 'dark'],
]) {
  for (const [breiteName, w, h] of BREITEN) {
    const ctx = await browser.newContext({
      ignoreHTTPSErrors: TLS_EGAL,
      viewport: { width: w, height: h },
      storageState: sitzung,
    });
    const page = await ctx.newPage();

    for (const [seiteName, pfad] of SEITEN) {
      const wo = `${seiteName} ${breiteName} ${modus}`;
      beobachte(page, wo);

      await page.goto(BASIS + pfad, { waitUntil: 'networkidle' });
      await page.evaluate(
        (t) => document.documentElement.setAttribute('data-theme', t),
        theme,
      );
      await page.waitForTimeout(400);

      // Zusicherung 1: Die Seite hat Inhalt. Eine blockierte API liefert
      // ein Gerüst ohne Zahlen -- das sähe im Screenshot fast normal aus.
      const text = (await page.locator('main').innerText().catch(() => '')) || '';
      if (text.trim().length < 40) {
        melde(wo, `Hauptbereich fast leer (${text.trim().length} Zeichen)`);
      }

      // Zusicherung 2: nichts läuft seitlich über.
      const ueberlauf = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      if (ueberlauf > 1) melde(wo, `${ueberlauf} px waagerechter Überlauf`);

      if (BILDER) {
        await page.screenshot({
          path: `${BILDER_ZIEL}/${seiteName}-${breiteName}-${modus}.png`,
          fullPage: w >= 1280,
        });
      }
    }
    await ctx.close();
  }
}

// Zusicherung 3: Auf jeder Breite ist genau eine Darstellung der
// Trade-Liste sichtbar. Beide wären doppelt, keine wäre die tote Zone.
console.log('Trade-Liste, genau eine Darstellung je Breite:');
for (const [name, w, h] of BREITEN) {
  const ctx = await browser.newContext({
      ignoreHTTPSErrors: TLS_EGAL,
      viewport: { width: w, height: h },
      storageState: sitzung,
    });
  const page = await ctx.newPage();
  await page.goto(BASIS + '/trades', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const tabelleAn = await page.locator('.td-tabelle').isVisible().catch(() => false);
  const kartenAn = await page.locator('.td-karten').isVisible().catch(() => false);
  const zeilen = await page.locator('.td-tabelle table tbody tr').count();
  const karten = await page.locator('.td-karten a').count();

  const genauEine = tabelleAn !== kartenAn;
  const hatInhalt = zeilen > 0 || karten > 0;
  const ok = genauEine && hatInhalt;

  console.log(
    `  ${name.padEnd(8)} ${String(w).padStart(4)}px  ` +
      `Tabelle ${tabelleAn ? 'an ' : 'aus'} (${String(zeilen).padStart(2)})  ` +
      `Karten ${kartenAn ? 'an ' : 'aus'} (${String(karten).padStart(2)})  ` +
      `${ok ? 'ok' : 'FEHLER'}`,
  );
  if (!genauEine) {
    melde(
      `Trades ${name}`,
      tabelleAn ? 'Tabelle und Karten gleichzeitig' : 'weder Tabelle noch Karten',
    );
  } else if (!hatInhalt) {
    melde(`Trades ${name}`, 'Darstellung sichtbar, aber ohne Zeilen');
  }
  await ctx.close();
}

// Zusicherung 4: Die Schrift kommt aus dem eigenen Verzeichnis und ist da.
{
  const ctx = await browser.newContext({
      ignoreHTTPSErrors: TLS_EGAL,
    viewport: { width: 1280, height: 900 },
    storageState: sitzung,
  });
  const page = await ctx.newPage();
  await page.goto(BASIS + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);

  const geladen = await page.evaluate(() => document.fonts.check('16px Archivo'));
  const ziffern = await page.evaluate(
    () => getComputedStyle(document.body).fontVariantNumeric,
  );
  console.log(`\nArchivo geladen : ${geladen ? 'ja' : 'NEIN'}`);
  console.log(`Ziffern-Feature : ${ziffern}`);

  if (!geladen) melde('Schrift', 'Archivo wurde nicht geladen');
  if (!ziffern.includes('tabular-nums')) {
    melde('Schrift', `tabular-nums fehlt (steht auf "${ziffern}")`);
  }
  await ctx.close();
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
