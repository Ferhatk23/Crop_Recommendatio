/**
 * Ein Auflöser, damit `node --test` denselben Quellcode lädt wie Next.js.
 *
 * Der Anwendungscode schreibt `import { outcome } from './outcome'` -- ohne
 * Endung, so wie es Bundler erwarten und wie es die tsconfig
 * (`moduleResolution: "bundler"`) vorschreibt. Node dagegen verlangt im
 * ESM-Modus die vollständige Dateiendung.
 *
 * Statt den Anwendungscode für den Testlauf zu verbiegen -- Endungen
 * anzuhängen würde `tsc` brechen, solange `allowImportingTsExtensions`
 * aus ist -- hängt dieser Hook die Endung erst bei der Auflösung an.
 * Getestet wird damit exakt die Datei, die auch ausgeliefert wird.
 */

const KANDIDATEN = ['.ts', '.tsx', '/index.ts', '/index.tsx'];

export async function resolve(specifier, context, nextResolve) {
  const relativ = specifier.startsWith('./') || specifier.startsWith('../');
  if (!relativ) return nextResolve(specifier, context);

  try {
    return await nextResolve(specifier, context);
  } catch (fehler) {
    if (fehler?.code !== 'ERR_MODULE_NOT_FOUND') throw fehler;
    for (const endung of KANDIDATEN) {
      try {
        return await nextResolve(specifier + endung, context);
      } catch {
        // nächster Kandidat
      }
    }
    throw fehler;
  }
}
