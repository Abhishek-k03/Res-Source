import type { Metadata } from "next";

import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Res-Source",
  description: "Multi-step research over your own corpora, with cited evidence.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin=""
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Caveat:wght@600;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Grain />
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

/** The canvas's fractal-noise overlay, at 3.5% over the whole page. */
function Grain() {
  return (
    <svg className="grain" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <filter id="noiseFilter">
        <feTurbulence
          type="fractalNoise"
          baseFrequency="0.9"
          numOctaves={2}
          stitchTiles="stitch"
        />
      </filter>
      <rect width="100%" height="100%" filter="url(#noiseFilter)" />
    </svg>
  );
}
