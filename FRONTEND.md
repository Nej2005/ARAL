# ARAL — Frontend Design Specification

The frontend for the app described in [BACKEND.md](BACKEND.md). It runs on **localhost**, works on **laptop and phone**, and has **light and dark mode**.

- **Prototype:** [design/prototype.html](design/prototype.html). This is a visual reference only; the real app is built in React (§3).

---

## 1. Principles

1. **One main action per screen**, as a filled button: *+ New* · *▶ Start exam* · *Check* / *Next* · *Retry mistakes*.
2. **A back arrow in the header** on every screen except Home. The app is only 3 levels deep: **Reviewers → Reviewer → Exam**.
3. **Secondary actions go in sheets** (a bottom sheet on phones, a dialog on laptops): exam options, export, rename/reset/delete, exit.
4. **Few words.** Buttons are an icon + one or two words. No instructions or explanations on screen unless something is blocked. Numbers over sentences (`20/58`, not "20 of 58 items reviewed").
5. **Lesson text is never restyled.** Questions, choices and quotes always appear in the readable mono, in sentence case, exactly as the backend sends them.

---

## 2. Visual style

**Black and white only. No other colors.** Grays are used only for secondary text and thin dividers.

| | Light mode — "exam sheet" | Dark mode — "terminal" |
|---|---|---|
| Background | white | black |
| Ink | black | white, with a faint glow |
| Extras | none | faint scanlines |

- **Type:** VT323 (pixel) for big titles, numbers and True/False; IBM Plex Mono for everything else.
- **Shapes:** square corners. 1px borders: solid for objects and selected states, dashed for inputs and unselected options.
- **Highlight blocks** (inverted text) for section labels and the question type.
- **ASCII touches:** a `////` or `****` rule between page sections, and `■■■■······` progress bars.

**States without color:**

| State | Look |
|---|---|
| Correct / selected | solid fill (black in light, white in dark) + `✓` |
| Wrong | diagonal stripes `////` + `✗` |
| Not answered | dashed outline |
| Current card (map) | extra outline |
| Disabled | 35% opacity |

### 2.1 Tokens (`src/styles/tokens.css`)

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `#000000` | page |
| `--surface` | `#FFFFFF` | `#0A0A0A` | card, sheets |
| `--fg` / `--accent` | `#000000` | `#FFFFFF` | text, borders, fills |
| `--on-accent` | `#FFFFFF` | `#000000` | text on fills |
| `--muted` | `#666666` | `#9C9C9C` | secondary text |
| `--rule` | `#D6D6D6` | `#2C2C2C` | row dividers |
| `--hatch` | black stripes 16% | white stripes 24% | wrong |
| `--glow-text` / `--glow-box` | none | faint white glow | dark only |
| `--scan` | transparent | `rgba(0,0,0,.28)` | scanlines, dark only |

### 2.2 Type scale
| Role | Font | Size |
|---|---|---|
| Page title | VT323 | 40–72px, uppercase |
| Score | VT323 | 96–170px |
| Section label | VT323 | 26px, in a highlight block |
| Question | Plex Mono | 17–21px |
| Body, choices | Plex Mono | 15px |
| Buttons, labels | Plex Mono | 11–13px, uppercase, letter-spaced |

### 2.3 Icons
Simple 24px line icons (2px stroke, square ends), inline SVG, `currentColor`:
`back` `next` `prev` `chevron` `plus` `x` `play` `check` `restart` `retry` `grid` `download` `upload` `more` `sun` `moon` `file` `skip` `edit` `trash` `reset`.
Icon-only buttons always have an `aria-label`.

---

## 3. Stack

| Concern | Choice |
|---|---|
| Framework | React 18 + Vite + TypeScript |
| Styling | Plain CSS: `styles/tokens.css` (§2.1) + `styles/global.css`, ported from the prototype. Tailwind was not needed |
| Routing | React Router (real URLs, so the browser back button works too) |
| Server data | TanStack Query, with polling while files are read and exams are made |
| Fonts | `@fontsource/vt323`, `@fontsource/ibm-plex-mono` (offline) |
| Dev server | `http://localhost:5173` → backend `http://localhost:8000/api/v1` (`VITE_API_URL`) |

---

## 4. Theme

- **One icon button** in the header: `☾` switches to dark, `☼` switches to light.
- The first visit follows the device setting. After a tap, the choice is saved in `localStorage` (`aral-theme`) and set as `data-theme` on `<html>`.
- An inline script in `index.html` applies the saved theme before React loads (no flash).

---

## 5. Responsive

| Width | Layout |
|---|---|
| < 700px (phone) | One column. Sheets slide up from the bottom. List rows stack their details on a second line. The flashcard's question map opens from the `grid` icon. |
| 700–899px | Same, with wider gutters (32px). Sheets become centered dialogs. |
| ≥ 900px (laptop) | Reviewer page shows Files and Exams side by side. Flashcards show the question map in a right-hand column. |

**The flashcard screen always fits the screen exactly:**
- The full height is `100dvh`, and the page itself never scrolls.
- The top bar (✕ · progress · map) and the bottom bar (← Back · Skip/Next) are always visible, padded for phone notches and home bars.
- Only the card's inside scrolls when the question plus feedback is long.

Nothing ever scrolls sideways. Touch targets are at least 44px.

---

## 6. Screens

### 6.1 Reviewers (home) — `/`
```
ARAL                                          ☾
REVIEWERS                              [+ NEW]
────────────────────────────────────────────────
Biology Midterm        ■■■······ 20/58   7/10  ›
2 files
Intro to Computing     ········· 0/31     —    ›
2 files · reading…
```
- **+ New** opens the *New reviewer* sheet: **Add files** (drop or pick) → the file list shows `Reading…` → `Ready` (or `Already uploaded · reused`) → name field (pre-filled from the first file) → **Create**. One line of fine print: "Files are read by Gemini (free tier). Avoid private files."
- API: `GET /reviewers`, `POST /documents`, `POST /reviewers`, poll `GET /documents/{id}`.

### 6.2 Reviewer — `/reviewers/:id`
```
←  REVIEWERS                                  ☾
BIOLOGY MIDTERM
■■■■■■■············· 20/58 reviewed
[▶ START EXAM]   [⇩ EXPORT]   [⋯]
////////////////////////////////////////////////
FILES                     [+ ADD]  │ EXAMS
□ Lesson 3 – Photo…  ■■■··· 12/34  │ Set 2 · MC        9/10  Oct 7  ›
□ Lesson 4 – Cell…   ■■■··· 8/24   │ Set 1 · MC·TF·ID  7/10  Oct 6  ›
```
- **▶ Start exam** opens the *New exam* sheet (§6.3). It's disabled while a file is still being read ("Waiting for 1 file to finish reading") or when nothing is left.
- **⇩ Export** → sheet: *Study sheet (PDF)*, *Flashcards (Anki CSV)*.
- **⋯** → sheet: *Rename*, *Reset progress* (asks first), *Delete*.
- **+ Add** → the same file picker as New reviewer.
- A past exam row → its latest results.
- API: `GET /reviewers/{id}`, `GET /reviewers/{id}/exams`, `POST /reviewers/{id}/export`, `POST /reviewers/{id}/coverage/reset`, `POST /reviewers/{id}/documents`, `PATCH`/`DELETE /reviewers/{id}`.

### 6.3 New exam (sheet)
```
NEW EXAM                                      ✕
TYPE
[ ABCD ]   [ T/F ]   [ ___ ]
 Multiple   True /    Identifi-
 choice     False     cation
ITEMS
[ − | 10 | + ]  / 38
› Choose slides or topics
[▶ START]
```
- Type tiles are toggles: filled = on, dashed = off. At least one must be on.
- The **/ 38** max updates live (`POST /reviewers/{id}/availability`).
- **Choose slides or topics** is collapsed by default. Inside: a checkbox per file with a `Slides 1 – 24` range, and topic chips. Leaving it closed = the whole reviewer.
- **▶ Start** → `POST /reviewers/{id}/exams` → the Making screen.

### 6.4 Making the exam — `/exams/:id/making`
A centered title, **MAKING 10 QUESTIONS**, with a filling `■■■■······` bar. It **opens the first card automatically** when the exam is ready (poll `GET /exams/{id}`), with no extra click. On failure: the error in one line + **Try again**.

### 6.5 Flashcards — `/attempts/:id`
```
✕            ■■■■······ 4/10               ▦
┌──────────────────────────────────────────┐
│ MULTIPLE CHOICE                       05 │
│ _____ is the process by which green      │
│ plants use sunlight to …                 │
│ [A] Fermentation                         │
│ [B] Photosynthesis                     ✓ │  ← solid fill
│ [C] Transpiration                      ✗ │  ← stripes
│ [D] Cellular respiration                 │
│ - - - - - - - - - - - - - - - - - - - -  │
│ [✗ WRONG]  Answer: Photosynthesis        │
│ Plants make their own food through …     │
│ Transpiration: the loss of water vapor … │
│ › Source · Lesson 3 · slide 4            │
└──────────────────────────────────────────┘
[← BACK]                          [NEXT →]
```
- **Top bar:** `✕` (exit sheet: *Finish now*, *Save & exit*, *Keep going*), progress, and `▦` question map (phones; laptops show the map as a side column, with a **Finish** button under it).
- **Answers:** MC rows with letter boxes · two big **TRUE** / **FALSE** blocks · Identification input `> Type the term` + **✓ Check**.
- **Feedback** (shown right after answering, only what's needed):
  1. Verdict: **✓ CORRECT** (solid) or **✗ WRONG** (striped) + `Answer: …`
  2. For a false T/F statement: ~~stroma~~ → **thylakoid membranes**
  3. One short reason
  4. When wrong: one line on what *your* answer actually is
  5. **› Source · Lesson 3 · slide 4**, collapsed. Tap to see the exact lesson quote.
- **Bottom bar:** **← Back** (answered cards are read-only) · **Skip ⏭** before answering, **Next →** after, **Results →** when everything is done.
- **Finish** with open cards → sheet: "3 open cards will count as wrong." **Answer them** / **Finish**.
- **Keyboard (laptop):** `A–D` / `1–4` choose · `T` / `F` · `Enter` next · `←` back · `→` skip/next · `Esc` close sheet. There are no hint labels on screen; the letter boxes on the choices are the hint.
- API: `GET /attempts/{id}`, `GET /attempts/{id}/cards/{index}`, `POST /attempts/{id}/answer`, `POST /attempts/{id}/finish`.

### 6.6 Results — `/attempts/:id/summary`
```
←  BIOLOGY MIDTERM                            ☾
SET 3
07/10
■■✗■■✗■■■□
[✗ RETRY 3 MISTAKES]  [↻ RESTART]  [+ NEW SET]
[⇩ EXPORT]
****************************************
REVIEW                                     3
✗ _____ best describes ATP …             ›
✗ The series of reactions in the stroma… ›
– _____ is the final electron acceptor … ›
```
- The **filled** button is the suggested next step: **Retry mistakes** when there are any, otherwise **New set**. **New set** is disabled when everything has been reviewed (use *Reset progress* in the reviewer's `⋯` menu).
- **Review** rows expand to show: the answer, your answer, the reason, and the source.
- **⇩ Export** → *Printable exam (PDF)*, *Flashcards (Anki CSV)*.
- API: `GET /attempts/{id}/summary`, `POST /attempts/{id}/retry-mistakes`, `POST /exams/{id}/attempts`, `POST /exams/{id}/next-set`, `GET /exams/{id}/export`.

---

## 7. Components

| Component | Notes |
|---|---|
| `Header` | Back arrow + parent name (or the logo on Home), theme icon. Hidden on the flashcard screen |
| `Button` | `primary` (filled), `secondary` (outlined), `ghost`, `icon` (44px square). Icon + 1–2 words |
| `Sheet` | Bottom sheet / dialog with a title and `✕`. Focus trap, `Esc` closes, tap outside closes. Never browser `confirm()` |
| `MenuList` | Full-width rows inside sheets (icon · label · short hint on the right) |
| `ListRow` | Clickable row that inverts on hover; stacks on phones |
| `MiniBar` | `■■■······` progress, with the numbers beside it |
| `FilePicker` | Dashed drop area + per-file status (`Reading…`, `Ready`, `Already uploaded · reused`, error) |
| `TypeTiles`, `Stepper`, `ScopePicker` | New exam sheet parts |
| `Flashcard` | `ChoiceList` / `TrueFalse` / `IdentInput` + `Feedback` |
| `Feedback` | Verdict, answer, change, reason, your-answer line, collapsible source |
| `QuestionMap` | Numbered cells (solid / striped / dashed) + a 3-item legend |
| `ScoreBlock`, `ResultStrip`, `ReviewList` | Results parts |
| `Toast` | One short line ("Saved · continue anytime", "Already uploaded · reused") |

---

## 8. States and messages

Short, one line, saying what to do:

| Situation | Shown |
|---|---|
| Loading | a filling `■■■······` bar, never a spinner |
| No reviewers | big **+ New** button with "No reviewers yet" |
| No exams | "No exams yet" |
| File being read | `Reading 60%` on the file row |
| `UNSUPPORTED_FILE_TYPE` | "Only PDF, PPTX or PPT" |
| `FILE_TOO_LARGE` | "Over 25 MB" |
| `NO_EXTRACTABLE_TEXT` | "No text found (scanned PDF?)" |
| `PPT_CONVERSION_UNAVAILABLE` | "Save as .pptx, or install LibreOffice" |
| `LLM_QUOTA_EXCEEDED` | "Gemini daily limit reached · try later" + **Retry** |
| `LLM_ERROR` | "Gemini didn't respond" + **Retry** |
| `DOCUMENTS_NOT_READY` | "Waiting for 1 file to finish reading" |
| `ALL_ITEMS_REVIEWED` | "All items reviewed" + **Reset progress** |
| `INVALID_SCOPE` | "Check the slide numbers" |

---

## 9. Accessibility

- Visible focus everywhere (2px dashed outline).
- Every icon-only button has an `aria-label`. Every state has a word or symbol, not just a fill.
- After answering, focus moves to the feedback and `aria-live` announces the verdict.
- Sheets trap focus and close with `Esc`.
- `prefers-reduced-motion` turns off the bar animation and smooth scrolling.

---

## 10. Project layout

```
frontend/
  index.html               # inline theme script
  src/
    main.tsx
    App.tsx                # routes
    api/                   # typed client + TanStack Query hooks
    styles/tokens.css      # §2.1
    styles/global.css
    components/            # §7
    icons/                 # §2.3
    screens/
      Reviewers.tsx
      Reviewer.tsx
      Making.tsx
      Flashcards.tsx
      Results.tsx
    sheets/
      NewReviewer.tsx
      NewExam.tsx
      Export.tsx
      ReviewerMenu.tsx
      ExitExam.tsx
    lib/theme.ts, lib/keyboard.ts
  tailwind.config.ts
  .env                     # VITE_API_URL=http://localhost:8000/api/v1
```

---

## 10b. Uploads, processing and passcode (added for hosting)

- **Uploads** go in 3 MB chunks (`src/api/upload.ts`): the file is hashed in the browser, duplicates are recognized before any bytes are sent, and each chunk is retried up to 3 times. Rows show *Checking… → Uploading 40% → Reading 2/5 → Ready*.
- **Processing is driven by the page** (`src/lib/driver.ts`): while a file or exam is pending, the app calls `POST …/process` repeatedly (one loop per item, shared across screens). Closing the tab pauses it; opening the reviewer again resumes it.
- **Passcode**: when `/health` reports `passcode_required`, a sheet asks once; the value is kept in `localStorage` (`aral-passcode`) and sent as `X-Passcode`. A 401 reopens the sheet.

## 11. Status

Built in [frontend/](frontend/) (Oct 2026). `npm run dev` serves it at http://localhost:5173 against the backend on :8000.
`frontend/e2e/flow.mjs` clicks through the whole flow in headless Chromium; screenshots are in [design/screenshots/](design/screenshots/).

## 12. Open questions

1. Should a card **move on by itself** after a correct answer (e.g. after 1.5s), or always wait for **Next**? Currently it always waits.
2. Sound effects for right/wrong? Currently none.
