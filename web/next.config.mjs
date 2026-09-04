/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  /**
   * Getrennte Ausgabeverzeichnisse für Entwicklung und Bau.
   *
   * `next build` schreibt sonst in dasselbe `.next`, aus dem ein
   * laufendes `next dev` gerade liest. Der Dev-Server bricht dann mit
   * `MODULE_NOT_FOUND` oder
   * `__webpack_modules__[moduleId] is not a function` ab und liefert
   * für jede Seite einen Fehler 500.
   *
   * Das Tückische daran: Es sieht aus wie ein Fehler in der App. Genau
   * so ist es hier passiert -- die Browser-Prüfung meldete "weder
   * Tabelle noch Karten" und "tabular-nums fehlt", und beides stimmte,
   * nur lag es nicht am Code. Man sucht dann an der falschen Stelle.
   *
   * `npm run build` setzt die Variable und baut nach `.next-build`;
   * `npm run dev` bleibt bei `.next`. Damit stören sie einander nicht
   * mehr, und beides kann nebeneinander laufen.
   */
  distDir: process.env.TD_DIST_DIR ?? '.next',
};
export default nextConfig;
