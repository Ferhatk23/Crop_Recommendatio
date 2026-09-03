import type { Metadata, Viewport } from 'next';
import './globals.css';
import { AppState } from '../components/AppState';
import { Shell } from '../components/Shell';

export const metadata: Metadata = {
  title: 'TradeDiary',
  description: 'Trading-Journal mit automatischer Übernahme aus MT5.',
  // Als App auf dem Home-Bildschirm — eigenes Icon, Vollbild ohne
  // Browser-Leiste, eigener Eintrag im App-Umschalter.
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, title: 'TradeDiary', statusBarStyle: 'default' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f3f2f2' },
    { media: '(prefers-color-scheme: dark)', color: '#171615' },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <head>
        {/* Die Schrift liegt lokal — kein CDN, kein Fremdabruf, kein
            Nachladen im Flugzeugmodus. */}
        <link
          rel="preload"
          href="/fonts/archivo-variable.woff2"
          as="font"
          type="font/woff2"
          crossOrigin=""
        />
      </head>
      <body>
        <AppState>
          <Shell>{children}</Shell>
        </AppState>
      </body>
    </html>
  );
}
