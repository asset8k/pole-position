# Pole Position frontend

React + TypeScript + Vite. Step 1 is a **visual-system preview**, not a working chat.
No backend calls, authentication, or conversation persistence are implemented yet.

## Run

```sh
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally http://127.0.0.1:5173).
Use Node 22.12+ LTS or Node 24 LTS for a consistent development/CI environment.

## Verify

```sh
npm run build
npm test
npx playwright install chromium
npm run test:browser
```

Browser tests capture desktop/mobile screenshots under `test-results/` for manual
visual review. They also check actual local font loading, keyboard focus, narrow
viewports, reduced motion, and that the preview sends no API requests. Screenshots
are review artifacts, not yet cross-platform pixel-diff baselines.

If Chrome is already installed, `PLAYWRIGHT_CHANNEL=chrome npm run test:browser`
can run the same checks without downloading a separate Chromium build.

## Visual system

- Hanken Grotesk for interface/readability; Barlow Condensed for the wordmark only.
- Locally served fonts; no runtime font CDN. Their original OFL licenses are in
  `public/fonts/`. Hanken: https://github.com/google/fonts/tree/main/ofl/hankengrotesk
  and Barlow: https://github.com/jpt/barlow.
- Warm white, charcoal, silver, and racing red. Tokens in `src/styles/tokens.css`.
- Clear/smoked glass for chrome; solid surfaces for reading. Blur-free fallback,
  reduced-transparency preference, and reduced-motion support included.
- Reusable `Button`, `Input`, and `GlassSurface`; native semantics and visible focus.

Next: replace the preview with the responsive shell and welcome composer (Step 2).
