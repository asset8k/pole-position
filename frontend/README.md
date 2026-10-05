# Pole Position frontend

React + TypeScript + Vite. Steps 1–5 provide the visual system, responsive welcome
screen, typed API layer, temporary guest chat, formatted answers, and source drawers.
Sending now calls `/api/chat`. Authentication and saved-conversation UI follow
in later steps; their API helpers are ready. Citations open a desktop side drawer
or mobile bottom sheet with the original retrieved excerpt.

## Run

```sh
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally http://127.0.0.1:5173).
Use Node 22.12+ LTS or Node 24 LTS for a consistent development/CI environment.
For live guest answers, run FastAPI separately from the project root:

```sh
uv run uvicorn pole_position.main:app --reload
```

Live sending uses your backend's configured OpenAI/Qdrant services and may incur
API costs. The frontend makes no model requests on page load or suggestion clicks.

## Verify

```sh
npm run build
npm test
npx playwright install chromium
npm run test:browser
```

Browser tests capture desktop/mobile screenshots under `test-results/` for manual
visual review. They also check actual local font loading, keyboard focus, narrow
viewports, reduced motion, and guest-chat flows with intercepted API requests. Screenshots
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

The old foundation showcase was replaced by the welcome screen; its reusable
primitives, font checks, contrast checks, and reduced-motion checks remain.

## API layer (Step 3)

- `src/api/contracts.ts` mirrors chat, citations, auth, messages, and conversations.
  Dates are ISO strings; TypeScript types do not validate JSON shapes at runtime.
- `src/api/endpoints.ts` provides `api.chat`, `api.auth`, and `api.conversations`.
  Protected helpers require an explicit token. There is no token storage yet.
- `src/api/client.ts` handles JSON, empty 204 responses, FastAPI validation errors,
  network failures, and cancellation. Mutations are never automatically retried.
  Validation errors discard backend `input`/`ctx` fields, which can contain passwords.

Requests default to same-origin `/api`. During development Vite forwards that
prefix unchanged to `http://127.0.0.1:8000`. To use another local backend port,
copy `.env.example` to `.env.local` **inside frontend/** and change
`API_PROXY_TARGET`. This setting is server-only, not a `VITE_` browser variable.
The backend's root `.env` is not used by the frontend. Never add service keys or
JWT signing secrets to the frontend.

The proxy is development-only. Production hosting must route `/api` to FastAPI,
or explicitly configure `createApiClient({ baseUrl: 'https://your-api/api' })`
and backend CORS at deployment time. No backend CORS change is needed now.

Guest chat sends previous history; registered chat will send a bearer token and an
optional conversation ID, omitting client history. The API layer passes the body
as supplied.

API tests use injected mock fetch functions, not OpenAI/Qdrant or a live database.

## Guest chat (Step 4)

- Messages and drafts live in React memory only: no local/session storage,
  IndexedDB, cookies, conversation IDs, or URL persistence. Refresh clears the chat.
- Follow-ups send the last ten **completed** user/assistant messages. The current
  question is sent separately. Failed attempts never enter outgoing history.
  History text is capped at the backend's 8,000-character limit; displayed answers
  and older messages remain intact in the current tab.
- Sending locks the composer and synchronously blocks duplicate submissions.
  A failed request restores the question for explicit resend; there are no automatic
  retries. New chat aborts pending work and ignores any late success or failure.
- Citations stay attached to their assistant message.
  Insufficient-evidence answers with empty citations are ordinary completed replies.

All automated guest-chat requests are mocked/intercepted. The tests do not call
OpenAI, Qdrant, or a live database. Backend files are unchanged.

## Answers and citations (Step 5)

- `AnswerContent` uses [react-markdown](https://github.com/remarkjs/react-markdown)
  and [remark-gfm](https://github.com/remarkjs/remark-gfm) for emphasis, lists, code,
  quotes, and horizontally scrollable tables. No raw-HTML plugin or HTML injection.
  Raw HTML stays escaped text; generated links and images are inert, preventing
  model-supplied navigation or remote image requests.
- A small syntax-tree transformer turns known `[S1]` markers into citation buttons.
  It does not transform code or links. Only that answer's validated, unambiguous
  source metadata can become clickable; missing markers remain plain text.
- Inline citation buttons and source chips open the same message-scoped source.
  Hover gives a compact document/page tooltip; click or keyboard activation opens
  the complete API `snippet` (the retrieved chunk), not a full PDF or necessarily
  an entire clause. No extra API/model request is made when opening a source.
- Source drawers show regulation title, section, clause/appendix/preamble reference,
  and exact PDF page/range. Excerpts remain literal text and are not shortened.
  No document URL is invented: the current API does not return a PDF URL.
- Native modal semantics, scroll locking, focus containment, Escape/backdrop/close
  dismissal, exact trigger-focus return, and a keyboard-scrollable excerpt area.
  Desktop side drawer, mobile bottom sheet, reduced-transparency fallback.

Tests include cross-message `S1` collisions, invalid/empty sources, raw HTML and URL
attacks, long excerpts, page ranges, keyboard focus, and narrow-screen tables.
All browser API responses are mocked. Next: authentication and sessions (Step 6).
