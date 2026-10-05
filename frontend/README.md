# Pole Position frontend

React + TypeScript + Vite. Steps 1–8 provide the visual system, responsive welcome
screen, typed API layer, temporary guest chat, formatted answers, source drawers,
authentication/session UI, and saved-conversation management. Sending calls `/api/chat`;
signed-in requests use the existing backend's automatic conversation saving. Saved
chats can be listed, reopened, renamed, and deleted. Citations open a desktop side drawer
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
npm run test:scripts
npm run test:production # Requires the build above; serves dist on port 5174
# Or run the complete sequence:
npm run check
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
  Protected helpers require an explicit token; session management owns token storage.
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

Guest chat sends previous history; registered chat sends a bearer token and an
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
All browser API responses are mocked.

## Authentication and sessions (Step 6)

- Compact login/registration dialogs, field requirements matching the backend,
  safe duplicate-username/credential errors, pending locks, and cancellation.
  Registration creates the user, then logs in and verifies `/auth/me`. If registration
  succeeds but sign-in fails, the UI offers sign-in rather than registering twice.
- Only the access token is stored under `pole-position:access-token` in **tab-scoped
  sessionStorage**. Refresh restores identity through `/auth/me`; no user identity is
  trusted from decoded JWT claims. Passwords, drafts, and transcripts aren't stored.
  If storage is blocked, sign-in works for the current page with an explicit notice.
- This is a compromise for the existing bearer-token backend: JavaScript can access
  sessionStorage. It is not an HttpOnly cookie or protection against all XSS. No JWT
  signing secret or service API key is shipped to the browser. Sessions are tab-scoped,
  not a cross-tab, persistent “remember me” feature.
- Expiry from a verified token schedules UI sign-out; protected 401 responses also
  clear the current session. Old-token errors cannot sign out a newer session.
  There is no refresh-token endpoint or automatic replay of a failed chat request.
- Network/server failures during restoration preserve the token and offer Retry or
  Continue as guest. Chat is blocked until that choice, preventing accidental guest
  requests while session verification is unresolved.
- Session changes remount the workspace, clearing transcripts, drafts, dialogs,
  and pending work; late responses cannot repopulate it. Guest messages are not
  silently imported into the account. Sign-out removes only this app's token;
  it does not delete saved conversations or revoke the server-side JWT.
- Signed-in chat sends a bearer token and optional conversation ID, **without client
  history**. The backend loads history and saves each successful turn. New chat starts
  without an ID. Refresh restores the session, not the displayed conversation yet;
  use the saved-conversation navigation to reopen any saved chat after refresh.

Unit/component and desktop/mobile browser tests mock all auth/chat responses.
No real user is registered and no OpenAI, Qdrant, or database call is made by tests.
Backend files remain unchanged.

## Saved conversations (Step 7)

- Signed-in users get a smoked-glass sidebar on desktop and **Saved chats** in the
  mobile navigation menu. The list loads from `GET /api/conversations`, sorted by
  update time. Guests never request or see saved conversations.
- Reopening uses `GET /api/conversations/{id}` and restores all ordered messages
  with their original per-message citations. It does not truncate the visible
  conversation to the ten messages used for backend query contextualization.
- Successful signed-in turns automatically refresh the list. Follow-ups send the
  selected ID and bearer token, never client history. Starting a new conversation
  omits the old ID; creation is still handled by the existing backend.
- Rename uses `PATCH` with a trimmed title, 1–160 characters. Delete requires a
  confirmation dialog, uses `DELETE`, and accepts its empty 204 response. Cancel
  makes no mutation. Deleting the selected chat returns to an empty composer;
  deleting another chat leaves the current transcript intact.
- Loading/error states block sending into an unresolved conversation. Unavailable
  or inaccessible details clear the prior transcript rather than leave misleading
  messages on screen. List, detail, and mutation failures offer explicit retries;
  failed mutations preserve the row and are never automatically replayed.
- Request cancellation plus request-identity checks protect list refreshes, detail
  loads, replies, and mutations from stale results. Logout unmounts all private
  state. No transcript, conversation list, selected ID, or title is stored in the
  browser. Refresh restores the session/list; choose a saved chat to resume it.
- Cancellation only stops client-side work. A mutation or generation already
  received by the backend may still complete; use Refresh saved chats to reconcile
  after interrupted requests. Access control remains enforced by the backend.
- Runtime shape checks reject malformed/cross-conversation messages and duplicate
  IDs. Mobile history and action dialogs preserve keyboard focus, Escape behavior,
  and scroll locking; source controls remain scoped to each restored message.

Unit/component tests cover older messages, ownership errors, ID mismatches, mutation
locks, refresh races, and logout cleanup. Desktop/mobile browser journeys cover
automatic creation, reopen/follow-up/refresh, rename, delete/cancel, retries, citations,
and 320–1440px layouts. All API requests are mocked/intercepted; no live account or
database is changed.

## Final integration and polish (Step 8)

- Replies follow the current turn while you are near the bottom. If you scroll up
  to read older passages while a reply is pending, your reading position is kept
  and **Jump to latest** appears. Sending explicitly follows the new turn. Open
  dialogs prevent background scrolling/focus changes; closing restores focus
  without jumping the page.
- Visual-viewport insets keep the mobile composer and dialogs inside the visible
  screen when the keyboard shrinks it. Pinch zoom is not treated as a keyboard.
  Safe-area padding, short-screen dialog scrolling, 16px mobile inputs, IME Enter
  handling, and a fallback when the viewport API is missing are included.
- Formatted headings stay beneath the chat heading; code blocks and tables can
  be scrolled with the keyboard. Skip navigation has a valid target while loading.
  High-contrast system colors, reduced motion, reduced transparency and existing
  blur-free CSS fallbacks preserve controls and reading surfaces.
- `polish.spec.ts` runs an entire guest → sign-in → saved-chat → reopen/follow-up
  → rename/delete → logout journey. It scans welcome, auth/error, chat/source,
  history/action and account states using axe WCAG A/AA checks, without disabling
  rules. It also checks older-reading scroll preservation, short-screen/reflow
  layouts, forced colors and reduced-transparency rendering.
- `test:production` starts Vite Preview against `dist` on **5174**, separate from
  development **5173**. It checks hashed assets, local fonts, follow-up requests,
  citations, accessibility, refresh cleanup and console/resource errors with
  intercepted APIs. Preview does not provide the development API proxy.

All automated suites mock/intercept API traffic. Keyboard resize is a deterministic
visual-viewport simulation and mobile projects are Chromium device emulation;
they are **not** physical-device Safari/Android keyboard verification. Reflow at
half a desktop viewport checks the layout equivalent of 200% zoom, not a browser
zoom gesture. Axe scans are automated checks, not an accessibility certification.
Before release, check actual phone keyboards and VoiceOver/NVDA, and confirm the
production host routes `/api` correctly. Screenshots are manually reviewed artifacts.

### Separate live smoke check

Start FastAPI from the repository root using the command in **Run**, then from
`frontend/`:

```sh
npm run smoke:live             # Only GET /api/health; no generation
npm run smoke:live -- --chat   # Explicit opt-in: one guest answer, API costs apply
```

The smoke script targets only `http://127.0.0.1:8000`. The optional chat verifies
the coordinate-system answer returns C2.1.1, usable citation fields and a null
conversation ID. It sends no bearer token and registers/saves nothing. This
direct-backend check is separate from production-host routing and answer-quality
evaluation; use the browser against the live backend for the final integration pass.
