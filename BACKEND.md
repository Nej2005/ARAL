# ARAL — Backend Specification

Backend for an app that turns lesson files (PDF / PowerPoint) into exam-style reviewers.
The frontend is designed later. This document defines everything the frontend will call.

---

## 1. What the backend must do

| # | Requirement | Where it is handled |
|---|---|---|
| R1 | Upload a **PDF** or **PowerPoint** (`.pptx`, `.ppt`) lesson file | §5 Ingestion |
| R2 | User picks the question type(s): **Multiple Choice**, **True or False**, **Identification** (definition → term) | §8 Generation |
| R3 | Questions must come from the lesson material, and their wording must stay **close to the original text** | §6 Source items, §9 Fidelity rules |
| R4 | User picks **how many items** the exam has | §8.1 Selection |
| R5 | After finishing, the user can **Restart** (same items) or **Generate a new set** made only of material that has **not been part of any earlier exam** | §10.3 After finishing |
| R6 | **Flashcard flow:** one question at a time. As soon as the user answers, show whether it is **right or wrong** plus a **short reason** why the answer is right (and, when wrong, why their choice is wrong) | §8.6 Feedback, §10.1 Flashcard flow |
| R7 | The user can **skip** a card and **go back** to earlier cards, but **cannot change** an answer | §10.1 Navigation rules |
| R8 | **Retry mistakes:** after finishing, retake only the cards that were wrong or skipped | §10.4 |
| R9 | **Optionally** limit an exam to certain files, slide/page ranges or topics. Without a selection, the whole reviewer is used | §7.2 Scope |
| R10 | **Don't reprocess** a file that was already uploaded | §5.5 Duplicates |
| R11 | **Combine several files into one reviewer** (e.g. Lessons 1–4 for a midterm) | §7 Reviewers |
| R12 | **Export** a printable PDF (exam or study sheet) and a CSV for flashcard apps like Anki | §11 Export |

### Assumptions (change these if they are wrong)

- **Runs on localhost only, for one user.** There is no login and no deployment. Every table still has an `owner_id`, so accounts could be added later without changing the data model.
- **Free LLM, no billing:** the Gemini API **free tier** (§13). The trade-offs are daily rate limits, and Google may use what is sent to it, so don't upload confidential files.
- **"Reviewed" is tracked per reviewer.** An item is "reviewed" once it has appeared in any exam of that reviewer, whatever its question type. If the same file is in two reviewers (e.g. "Lesson 3" and "Midterm"), each reviewer tracks its own coverage.
- The user can pick **one or more** question types for a single exam (e.g. 20 items mixed MCQ + T/F).
- Scanned (image-only) PDFs are **not** supported in the MVP. They are rejected with a clear error (§5.4).

---

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language / framework | **Python 3.11+ + FastAPI** | Best libraries for PDF/PPTX parsing; async; auto OpenAPI docs for the frontend |
| Database | **SQLite** (one file on disk) via **SQLAlchemy 2.x** + **Alembic** | Nothing to install or run; enough for one user on localhost |
| Validation | **Pydantic v2** | Request/response schemas and LLM output schemas |
| PDF text | **PyMuPDF** (`pymupdf`) | Fast, keeps reading order and line breaks |
| PPTX text | **python-pptx** | Slide titles, bullet levels, tables |
| `.ppt` (legacy) | **LibreOffice headless** converts `.ppt` → `.pptx`, then python-pptx | python-pptx cannot read `.ppt` |
| Fuzzy matching | **rapidfuzz** | Fidelity checks and answer grading |
| LLM | **Google Gen AI SDK** (`google-genai`), model `gemini-3.8-flash` on the **free tier** | Fact extraction, distractor choice, True/False falsification, rationales. Free, with no credit card needed (§13) |
| PDF export | **fpdf2** + a bundled Unicode font (Noto Sans) | Pure Python, no system libraries; handles ñ, é, etc. |
| CSV export | Python `csv` module | Anki-compatible text import |
| Processing | **Steps driven by the client**: `POST …/process` runs one step (one Gemini call) and returns; the frontend repeats until `ready`. No background jobs | Works the same on localhost and on a serverless host (Vercel); progress is saved per step |
| File storage | **In the database** (`document_files`), uploaded in 3 MB chunks; the bytes are deleted once the pages are read | No disk or file service needed; fits the 4.5 MB request limit of serverless hosts |
| Tests | **pytest** + fixture files + mocked LLM client | |

---

## 3. Project layout

```
backend/
  app/
    main.py                 # FastAPI app, routers, error handlers
    config.py               # Settings loaded from env (pydantic-settings)
    db.py                   # Engine, session
    models/                 # SQLAlchemy models (§4)
    schemas/                # Pydantic request/response models (§12)
    api/
      documents.py
      reviewers.py
      exams.py
      attempts.py
      exports.py
    services/
      ingestion/
        pdf.py              # PDF → pages
        pptx.py             # PPTX → slides
        ppt_convert.py      # .ppt → .pptx via LibreOffice
        dedupe.py           # same-file / same-text detection (§5.5)
      knowledge.py          # pages → source items (Gemini) + validation
      scope.py              # optional file / page / topic filter (§7.2)
      generation/
        selector.py         # pick unused items, split across types
        identification.py
        true_false.py
        multiple_choice.py
      fidelity.py           # all "stay close to the source" checks
      grading.py
      export/
        pdf_exam.py         # printable exam + answer key
        pdf_study_sheet.py  # printable term/definition sheet
        anki_csv.py
      llm.py                # the only module that talks to Gemini
    assets/fonts/           # NotoSans-Regular.ttf, NotoSans-Bold.ttf
    jobs.py                 # background job runners + status updates
  alembic/
  tests/
    fixtures/               # sample.pdf, sample.pptx, sample.ppt
  pyproject.toml
  .env.example
```

---

## 4. Data model

```
documents ──< document_pages                      (the file library; one row per unique file)
    │
    └──< source_items                              (the "facts" extracted once per document)

reviewers ──< reviewer_documents >── documents     (a reviewer combines 1..n documents)
    │
    └──< exams ──< questions >── source_items
            │
            └──< attempts ──< answers >── questions
```

### `documents`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid, nullable | for future auth |
| filename | text | original name |
| file_type | enum `pdf` \| `pptx` \| `ppt` | |
| storage_path | text | |
| sha256 | text | hash of the file bytes. **Unique with `owner_id`** (§5.5) |
| text_sha256 | text, nullable | hash of the normalized extracted text (§5.5) |
| extraction_version | int | version of the extraction prompt/rules that produced the items |
| copied_from_document_id | FK, nullable | set when items were copied from an identical-text document |
| extraction_progress | int, default 0 | number of extraction windows finished; lets a stopped job resume (§6.2) |
| status | enum `uploaded` \| `extracting` \| `ready` \| `failed` | |
| error_code / error_message | text, nullable | set when `failed` |
| page_count | int | pages or slides |
| created_at | timestamp | |

### `document_pages`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| document_id | FK | |
| page_no | int | 1-based page or slide number |
| title | text, nullable | slide title / first heading |
| text | text | extracted text, **original wording and line breaks kept** |

### `source_items`
The unit of review. Every question is built from exactly one source item, and "reviewed" is tracked per source item.

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| document_id | FK | |
| page_no | int | where it was found |
| kind | enum `definition` \| `fact` | see §6 |
| term | text, nullable | required for `definition`; the key term/value for `fact` |
| aliases | json list | e.g. acronym + full form found in the document |
| body | text | the definition (for `definition`) or the full statement (for `fact`) |
| source_quote | text | the exact span from `document_pages.text` that contains term + body |
| quote_start / quote_end | int | character offsets of `source_quote` inside the page text |
| topic | text, nullable | slide title / section heading, as written |
| topic_key | text, nullable | normalized topic used for grouping and scope (§7.2) |
| superseded_at | timestamp, nullable | set when the document is reprocessed (§5.5); superseded items are kept for old exams but never selected again |
| created_at | timestamp | |

### `reviewers`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid, nullable | |
| title | text | e.g. "Biology Midterm" |
| coverage_epoch | int, default 0 | bumped when the user resets "reviewed" coverage (§10.3) |
| created_at / updated_at | timestamp | |

### `reviewer_documents`
| column | type | notes |
|---|---|---|
| reviewer_id | FK | PK together with `document_id` |
| document_id | FK | |
| position | int | display order of the files inside the reviewer |
| added_at | timestamp | |

### `exams`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| reviewer_id | FK | |
| owner_id | uuid, nullable | |
| question_types | json list | subset of `["mcq","true_false","identification"]` |
| requested_count | int | what the user asked for |
| actual_count | int | what could be generated (may be lower, §8.1) |
| scope | json, nullable | the optional filter used (§7.2); `null` = whole reviewer |
| coverage_epoch | int | copied from the reviewer when created |
| parent_exam_id | FK, nullable | set when created via "new set" |
| status | enum `generating` \| `ready` \| `failed` | |
| created_at | timestamp | |

### `questions`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| exam_id | FK | |
| source_item_id | FK | |
| type | enum `mcq` \| `true_false` \| `identification` | |
| position | int | default order (used for the printable exam) |
| prompt | text | question text shown to the user |
| choices | json list, nullable | MCQ only: `[{"id":"c1","text":"...","source_item_id":"..."}]`. The IDs stay the same; the A–D letters are assigned per attempt by display order |
| correct_answer | text | MCQ: choice id; T/F: `"true"`/`"false"`; Identification: the term |
| accepted_answers | json list | Identification: term + aliases |
| rationale | text | short "why this is the answer" (1–2 sentences, §8.6), shown after answering |
| choice_feedback | json map, nullable | MCQ only: `choice_id → "why this option is wrong"` for each distractor (§8.6) |
| explanation | json | `{"source_quote": "...", "document_id": "...", "page_no": 4, "changed_span": {...}}` |

### `attempts`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| exam_id | FK | |
| attempt_no | int | 1, 2, 3… per exam |
| kind | enum `full` \| `mistakes` | `mistakes` = a Retry-mistakes round (§10.4) |
| source_attempt_id | FK, nullable | for `mistakes`: the attempt whose wrong/skipped cards it contains |
| question_order | json list of question ids | shuffled per attempt; for `mistakes`, only the wrong + skipped questions |
| choice_orders | json map `question_id → [choice ids]` | MCQ choices reshuffled per attempt |
| last_viewed_index | int, default 1 | 1-based position in `question_order` of the last card opened; used to resume |
| status | enum `in_progress` \| `completed` | becomes `completed` when every card is answered, or when the user presses Finish |
| correct_count / total | int | `correct_count` is updated after every answer |
| started_at / completed_at | timestamp | |

### `answers`
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| attempt_id | FK | |
| question_id | FK | unique with `attempt_id`; an answer is **final** once sent (no changing it). A skipped card simply has no row yet |
| response | text | the user's answer |
| is_correct | bool | graded immediately when the answer is sent |
| match_note | text, nullable | e.g. `"typo_tolerated"` for Identification |
| answered_at | timestamp | |

**"Used" items are derived, not stored separately:**
the items used in a reviewer are the distinct `questions.source_item_id` of that reviewer's exams where `exams.coverage_epoch = reviewers.coverage_epoch` and `exams.status = 'ready'`.

---

## 5. Ingestion (upload → pages)

### 5.1 Flow
**Upload (chunked, from the browser):**
1. The browser hashes the file (SHA-256) and calls `POST /uploads` with `{filename, size, sha256, reviewer_id?}`. The extension and size (`MAX_UPLOAD_MB`, default 25) are checked. **If the same file already exists**, the response says `duplicate: true` with the existing document and nothing is uploaded (§5.5).
2. `PUT /uploads/{id}/chunks/{n}` sends the file in 3 MB chunks (`UPLOAD_CHUNK_MB`).
3. `POST /uploads/{id}/complete` assembles the chunks, verifies the size and hash, checks the file's magic bytes, stores the bytes in `document_files`, creates the `documents` row with `status=uploaded`, and links it to the reviewer if one was given. Returns `202`.

`POST /documents` (single multipart request) does the same in one call; it is used by scripts and tests.

**Processing (steps driven by the client):** the frontend calls `POST /documents/{id}/process` until `done` is true.
- Step 1 reads the file into `document_pages` (§5.2), computes `text_sha256`, and deletes the stored bytes. **If the same text was already processed**, the items are copied and the document is `ready` (§5.5).
- Each further step runs one extraction window (§6.2) and saves its items.
- After the last window: `status=ready`, or `failed` + `error_code` if nothing was found. On any error: `status=failed` + `error_code`.
- A step holds a claim (`step_started_at`) for at most `STEP_CLAIM_SECONDS`; a second caller during that time gets the current state back without doing work (`busy: true`).

### 5.2 Extraction rules — keep the original formatting
- **PDF:** use `page.get_text("text", sort=True)` per page. Keep line breaks. Join words hyphenated across a line break (`infor-\nmation` → `information`). Drop the page headers and footers that repeat on more than 50% of the pages.
- **PPTX:** for each slide, put the title first, then the text frames in reading order (top → bottom, left → right). Keep bullet levels as indentation (`"  " * level + "• "`). Write tables row by row as `cell | cell | cell`, so two-column term | meaning tables can be read as definitions. Ignore speaker notes in the MVP; they can be added later behind a flag.
- **PPT:** run `soffice --headless --convert-to pptx` into a temp folder, then use the PPTX path. If LibreOffice is missing, fail with `PPT_CONVERSION_UNAVAILABLE`.
- Store the text **as extracted**. Normalization (lowercasing, collapsing whitespace) is applied **only inside comparisons**, never to the stored text.

### 5.3 Pages that are skipped as content
Title-only slides, table of contents, "Objectives" lists with no definitions, references/bibliography, and "Thank you / Questions?" slides. These are still stored, but the extraction prompt is told to ignore them.

### 5.4 Failure codes
| code | when |
|---|---|
| `UNSUPPORTED_FILE_TYPE` | not pdf/pptx/ppt |
| `FILE_TOO_LARGE` | over `MAX_UPLOAD_MB` |
| `NO_EXTRACTABLE_TEXT` | under ~200 characters of text in total (likely a scanned PDF or image-only slides) |
| `PPT_CONVERSION_UNAVAILABLE` / `PPT_CONVERSION_FAILED` | LibreOffice problem |
| `NO_SOURCE_ITEMS` | text exists but no definitions or facts were found |
| `LLM_ERROR` | Gemini call failed after retries |
| `LLM_QUOTA_EXCEEDED` | the free-tier daily limit was reached; progress is saved, try again later (§13.2) |

### 5.5 Duplicates — don't reprocess the same file
Processing a file costs Gemini calls, so the backend checks twice for work it has already done:

| Check | When | If it matches |
|---|---|---|
| **1. Same file** (`sha256` of the bytes) | On upload, before anything is saved | No new document is created. The response is `200 { id: <existing id>, status, duplicate: true }`. If a `reviewer_id` was sent, the existing document is added to that reviewer (doing nothing if it is already there). **Exception:** if the existing document is `failed`, extraction is run again on that same row (`202`). |
| **2. Same text, different file** (`text_sha256` of the normalized page texts) | After page extraction (e.g. the same slides saved again, which changes the bytes but not the text) | If a `ready` document with the same `text_sha256` and the same `extraction_version` exists, its source items are **copied** (no Gemini calls), and `copied_from_document_id` is set. |

**Manual reprocess (the only way to force it):** `POST /documents/{id}/reprocess`. Use it when the extraction rules have improved (`GET /documents/{id}` shows `outdated: true` when `extraction_version` is older than the current one) or when the extraction was bad.
- The old items get `superseded_at` and are kept, so old exams and attempts still display correctly.
- The new items have new ids, so in coverage they count as **unused**.

---

## 6. Source items (pages → reviewable facts)

This runs **once per document**, right after upload. Every exam is built from these items, so generating an exam later is fast and needs little LLM work.

### 6.1 Item kinds
| kind | example from a lesson | usable for |
|---|---|---|
| `definition` | "**Photosynthesis** is the process by which green plants use sunlight to synthesize food from carbon dioxide and water." | Identification, MCQ, True/False |
| `fact` | "The mitochondria is known as the powerhouse of the cell." (key term: *mitochondria*) | MCQ, True/False |

Identification uses **only `definition` items**, as the requirement says (identification based on definition).

### 6.2 Extraction with Gemini
- The pages are sent in windows of about 15 pages (`EXTRACTION_WINDOW_PAGES`), with a 1-page overlap so that definitions split across pages are not lost.
- Items are saved **after each window**, and the document records the last finished window. If the free-tier limit stops the job, it resumes from the next window instead of starting over (§13.2).
- Each call uses **structured output** (a Pydantic model), so the response is always valid JSON:

```python
class ExtractedItem(BaseModel):
    kind: Literal["definition", "fact"]
    page_no: int
    term: str                 # the term being defined / the key term in the fact
    aliases: list[str]        # other names for the term that appear IN THE DOCUMENT
    body: str                 # definition text or full statement
    source_quote: str         # copied character-for-character from the page text
    topic: str | None         # slide title / section heading

class ExtractionResult(BaseModel):
    items: list[ExtractedItem]
```

- Prompt rules given to Gemini (summary):
  1. Copy `source_quote`, `term` and `body` **verbatim** from the page text. Do not paraphrase, fix grammar or summarize.
  2. `term` and `body` must both be substrings of `source_quote`.
  3. One item per distinct definition or fact. Skip opinions, examples, instructions, and the slide types listed in §5.3.
  4. `aliases` may only contain names that actually appear in the document (e.g. "CPU" for "Central Processing Unit").
  5. A table row of the form `term | meaning` is a `definition`.

### 6.3 Validation after extraction (backend, not the LLM)
Each extracted item is checked by `fidelity.validate_item()`:
1. **Find the quote in the page.** Look for an exact substring match after whitespace normalization. If there is none, use the best fuzzy span (`rapidfuzz.fuzz.partial_ratio ≥ 95`) and **replace** `source_quote` with the real span from the page. The stored quote always comes from the document, never from the model.
2. Save `quote_start` / `quote_end`.
3. `term` and `body` must be found inside the (snapped) quote. If not, the item is **dropped**.
4. **Deduplicate:** the same normalized term plus a similar body (ratio ≥ 90) is merged, keeping the first occurrence and combining the aliases.
5. Compute `topic_key` (§7.2).

Dropped items are logged with the reason, so the prompts can be tuned.

---

## 7. Reviewers (combining files) and scope

### 7.1 Reviewers
A **reviewer** is what the user studies. It contains **one or more documents**, e.g. "Lesson 3" (one file) or "Biology Midterm" (Lessons 1–4).

- Documents live in the user's **file library**. One document can be in several reviewers without being processed again.
- **Exams belong to a reviewer** and draw items from **all of its documents**. MCQ distractors and the Identification "other term" lookup (§8.6) also use the whole reviewer.
- Every source reference shown to the user names the **file and the page/slide**, e.g. *"Lesson 3 – Photosynthesis.pptx, slide 4"*.
- **Adding** a document to a reviewer that already has exams is allowed: its items are simply unused.
- **Removing** a document from a reviewer is allowed: its items are no longer picked, and old exams still work.
- Exams can only be created when **every** document in the reviewer is `ready` (`409 DOCUMENTS_NOT_READY`, listing the documents that are not ready). A failed document must be removed or reprocessed first.
- Typical frontend flow: upload one or more files → create a reviewer with those document ids. For a single file, the frontend can upload it with no `reviewer_id` and then create the reviewer, or create the reviewer first and upload into it.

### 7.2 Scope — optional
By default, an exam covers **the whole reviewer**. The user can **optionally** narrow it:

```json
"scope": {
  "documents": [
    { "document_id": "d1" },                              // the whole file
    { "document_id": "d2", "pages": [[5, 20], [25, 25]] } // slides 5–20 and slide 25
  ],
  "topics": ["Cell Structure", "Photosynthesis"]
}
```

Rules:
- `scope` omitted or `null` → **whole reviewer** (the default; the frontend can hide the scope picker behind an "Advanced" toggle).
- `documents` only → items from those documents (and page ranges, if given).
- `topics` only → items whose `topic_key` matches, from any document.
- Both → items that match **both**.
- Validation → `422 INVALID_SCOPE`: the document must be in the reviewer, the page ranges must be within `page_count`, and the topics must exist in the outline.
- **Topic grouping:** `topic_key` = the topic casefolded, with whitespace collapsed and continuation markers like "(cont.)", "(continued)" or "– Part 2" removed. "Cell Structure (cont.)" and "Cell Structure" are then one topic. The display name is the first `topic` seen.
- `GET /reviewers/{id}/outline` returns what the scope picker needs: each document's pages/slides (number, title, item count) and the list of topics (with total and unused item counts).
- A **new set** keeps the parent exam's scope unless the request sends a different `scope` (sending `"scope": null` explicitly means the whole reviewer).
- Scope only filters which items are **selected**. MCQ distractors may still come from anywhere in the reviewer, though the same topic is preferred.

---

## 8. Exam generation

### 8.1 Selection — `selector.py`
Input: `reviewer_id`, `types` (1–3 types), `count`, optional `scope`.

1. `pool = non-superseded source_items of the reviewer's documents`, filtered by `scope` (§7.2).
2. `unused = pool − items used in the reviewer's current coverage epoch` (§4).
3. **Split `count` across the selected types** as evenly as possible (the remainder goes to the first types in the list).
4. **Fill the most constrained type first:** Identification takes `definition` items only, then True/False and MCQ take from what is left (any kind). Items are picked in random order, but spread across documents and pages (round-robin by `(document, page_no)`) so one exam covers all the material instead of clustering on the first slides of the first file.
5. If a type cannot be filled, move its shortfall to the other selected types.
6. If the total is still short, generate **as many as are available**: `actual_count < requested_count`, and the response includes `"shortfall": n`.
7. If **0** items are available → `409 ALL_ITEMS_REVIEWED`. The error includes `unused_outside_scope`, so that when a scope was used, the frontend can suggest widening it instead of resetting coverage (§10.3).

`POST /reviewers/{id}/availability` exposes these numbers **before** generating, so the UI can cap the "number of items" input.

### 8.2 Identification — deterministic, no LLM
- `prompt` = the item's `body` (the definition) **as written in the document**.
- If the term itself appears in the definition, replace it with `_____`.
- `correct_answer` = `term`; `accepted_answers` = `[term, *aliases]`.

### 8.3 Multiple Choice — mostly deterministic
There are two stem formats. One is chosen at random per question, for variety:

| format | stem | correct option | distractors |
|---|---|---|---|
| **A. Fill-in** (any item) | `source_quote` with the term replaced by `_____` | the term | 3 other **terms** from the reviewer |
| **B. Term → meaning** (`definition` only) | "Which of the following best describes **{term}**?" | the item's `body` verbatim | 3 other items' **bodies** verbatim |

- Distractors are **taken from the same reviewer** (other items' terms or bodies). The stem and every option are therefore real lesson text.
- **Choosing which distractors:** one Gemini call per exam picks the 3 most plausible candidates for each question from the reviewer's item list (same topic and same "type of thing" preferred). Structured output: `{question_ref, distractor_item_ids[3]}`. The backend checks that the IDs exist and are not the correct item.
- **Fallback:** if the reviewer has fewer than 4 usable candidates, Gemini writes the missing distractors. These are flagged `explanation.generated_distractors = true`.
- Options are stored with stable ids (`c1`–`c4`). Every attempt shuffles their display order (§10), and the frontend labels them A–D in that order.

### 8.4 True or False — one controlled edit
- About 50% True and 50% False per exam (randomized, never all the same).
- **True:** `prompt` = the `source_quote` (or `body` for long quotes) **exactly as written**.
- **False:** Gemini returns **one replacement**, not a rewritten sentence:

```python
class Falsification(BaseModel):
    original_span: str     # must appear exactly in the statement
    replacement: str       # preferably another term from this reviewer,
                           # or a changed number, or a negation
    reason: str            # why the edited statement is false
```

  The backend builds the false statement itself: `statement.replace(original_span, replacement, 1)`. Everything else in the sentence stays the same as the source. Checks:
  - `original_span` exists in the statement, and `replacement` ≠ `original_span`
  - the edited statement is not identical to another true item in the reviewer (otherwise the edit could accidentally be true)
  - `explanation.changed_span = {"from": original_span, "to": replacement}`, so the feedback can show what was changed

### 8.5 Generation step
`POST /reviewers/{id}/exams` → creates the exam with `status=generating` → returns `202`. The frontend then calls `POST /exams/{id}/process`, which builds the whole exam in one step:
1. selection (§8.1)
2. builds the Identification questions directly
3. **one** batched Gemini call for all MCQ distractor picks, all T/F falsifications and all rationales in this exam (§8.6), split into batches of ~25 questions if needed
4. builds the deterministic feedback parts (§8.6)
5. fidelity checks (§9). A question that fails is rebuilt once with another unused item, if one exists
6. `status=ready`

### 8.6 Feedback content (built at generation time)
All feedback is prepared **when the exam is generated**, so showing it after an answer is instant and needs no LLM call.
Every feedback has three parts:

| Part | What it says | How it is built |
|---|---|---|
| **Verdict** | Correct / Wrong, plus the correct answer | Grading (§10.2) |
| **Why** (`rationale`) | 1–2 sentences, max ~40 words, on why the correct answer is right | Gemini, in the same batched call as §8.5. It may use **only** the source item's text (and, for MCQ, the distractor items' text). |
| **From the lesson** | The verbatim `source_quote` + file name + page/slide number | Copied from the source item |

Extra part shown **only when the user is wrong**, saying why *their* answer is wrong:

| Type | "Why your answer is wrong" | How it is built |
|---|---|---|
| MCQ | Each distractor comes from another lesson item, so its feedback is that item's own meaning, e.g. *"Respiration refers to the process of breaking down glucose to release energy (Lesson 4.pptx, slide 7)."* | Deterministic: the distractor's `term` + `body` + file + `page_no` (stored in `choice_feedback`). For Gemini-written distractors (§8.3 fallback), Gemini writes this sentence too. |
| True/False — statement was **false** | *"The statement changed **'chloroplast'** to **'mitochondria'**."* + Gemini's `reason` | Deterministic from `changed_span`, plus `Falsification.reason` |
| True/False — statement was **true** | No extra part; the rationale and the quote show that it is accurate | — |
| Identification | If the user's answer matches **another term in the reviewer**, show that term's meaning: *"'Osmosis' is a different concept: … (Lesson 2.pdf, p. 5)"*. Otherwise only the correct answer and the rationale are shown. | Deterministic, at answer time: fuzzy-match the response against the reviewer's other item terms (`ratio ≥ 90`) |

Rationale structured output (added to the §8.5 batch):

```python
class QuestionRationale(BaseModel):
    question_ref: str
    rationale: str            # 1–2 sentences, ≤ 40 words, grounded in the given source text
```

If a rationale fails the checks in §9, the template **"The lesson states: '{source_quote}'"** is used instead, so feedback is never missing.

---

## 9. Fidelity rules ("wording should not differ too much")

All of these live in `services/fidelity.py` and have unit tests.

| Question part | Rule | Check |
|---|---|---|
| Identification prompt | Definition text from the document; only the term may be blanked | prompt (with `_____` filled back in) == `body` |
| MCQ fill-in stem | Source quote with one blank | stem (blank filled back in) == `source_quote` |
| MCQ term → meaning | Template + verbatim body | correct option == `body` |
| MCQ options | Real lesson text | each option == some item's `term` or `body`, unless flagged as generated |
| True statement | Verbatim | == `source_quote` / `body` |
| False statement | Exactly one span changed | token-level diff touches only `original_span`; `fuzz.ratio(false, true) ≥ 70` |
| Rationale | Short and grounded in the lesson | non-empty, ≤ 40 words, does not contradict the correct answer (it must not contain the T/F `replacement` text presented as true), and every quoted phrase (text in quotation marks) appears in the reviewer's documents. Otherwise the template fallback (§8.6) is used |

Allowed light cleanup, applied **only to the displayed prompt**: trimming whitespace, removing a leading bullet character, and joining wrapped lines. Never rewording.

---

## 10. Attempts: flashcards, Restart, Retry mistakes, New set

### 10.1 Flashcard flow (one question at a time)

```
start attempt ──► card 1 ──answer──► feedback ──Next──► card 2 ──Skip──► card 3 ──► …
                    ▲                                     ▲                  │
                    └────────────── Back ─────────────────┴──────────────────┘

all cards answered ──► summary            Finish (with skipped cards) ──► confirm ──► summary
                                                                                        │
                                                    Restart / Retry mistakes / New set ◄┘
```

1. `POST /exams/{id}/attempts` starts an attempt, shuffles the question order and MCQ choice order, and returns **card 1**.
2. The user answers. `POST /attempts/{id}/answer` grades it **immediately**, saves it, and returns the **feedback** (§8.6) plus progress.
3. The user moves with **Next**, **Back** or **Skip**. All three just open another card with `GET /attempts/{id}/cards/{index}`; there is no separate "skip" call.
4. The attempt **completes automatically** when the last unanswered card is answered (`"finished": true` in the feedback response).
5. The user can also press **Finish** early → `POST /attempts/{id}/finish`. Any skipped cards are counted as not correct (§10.3).
6. `GET /attempts/{id}/summary` returns the score and the after-finishing options.

#### Navigation rules
- **Skip:** opening another card without answering leaves the current card unanswered. The user can come back to it any time before the attempt completes.
- **Back:** opening an **answered** card shows it **read-only, with its answer and feedback**. An answer is final, because the user has already seen the correct answer (`409 ALREADY_ANSWERED` if they try again).
- **Next after the last card:** if skipped cards remain, the frontend jumps to the first one (`next_unanswered_index` is included in every card and feedback response). If none remain, the attempt is already complete.
- **Question map:** `GET /attempts/{id}` returns the status of each card (`unanswered` / `correct` / `wrong`, without content), so the frontend can show a grid of numbered cards to jump to.
- **No answers leak:** a card's correct answer and feedback are sent only after that card is answered, or after the attempt is completed.
- **Resumable:** opening an in-progress attempt continues at `last_viewed_index`.

### 10.2 Grading — `grading.py` (runs on every answer)
- **MCQ:** compare the chosen choice id with `correct_answer`.
- **True/False:** compare the boolean.
- **Identification:** normalize both sides (casefold, strip punctuation, collapse spaces, remove leading "the/a/an"):
  - exact match with any of `accepted_answers` → correct
  - else `fuzz.ratio ≥ IDENT_FUZZY_THRESHOLD` (default 90) → correct, `match_note="typo_tolerated"`
  - else → wrong

### 10.3 After finishing: the choices
The summary (`GET /attempts/{id}/summary`) returns:
- the score: `correct_count / total`, where skipped cards count as not correct
- the cards answered **wrong** and the cards **skipped**, each with the correct answer and full feedback, so the user can review them
- `retry_mistakes.count` (wrong + skipped) for the Retry mistakes button, and `next_set.unused_items` for the New set button

| User action | Endpoint | What happens |
|---|---|---|
| **Restart** | `POST /exams/{id}/attempts` | New `full` attempt on the **same questions**, with a new question order and choice order, starting again at card 1. Earlier attempts are kept for history. |
| **Retry mistakes** | `POST /attempts/{id}/retry-mistakes` | New `mistakes` attempt with **only the wrong + skipped cards** of this attempt (§10.4). |
| **Generate a new set** | `POST /exams/{id}/next-set` (body: optional `types`, `count`, `scope`; defaults to the parent exam's) | New exam built **only from items not used in any exam** of this reviewer in the current coverage epoch. `parent_exam_id` links it to the previous exam. |
| *(when everything has been reviewed)* | `POST /reviewers/{id}/coverage/reset` | Increments `reviewers.coverage_epoch`, so all items count as unused again. Old exams and attempts stay as they are. |

`next-set` returns `409 ALL_ITEMS_REVIEWED` when nothing is left, and a `shortfall` when only part of the requested count is available.

### 10.4 Retry mistakes
- Only allowed on a **completed** attempt (`409 ATTEMPT_NOT_FINISHED`) that has at least one wrong or skipped card (`409 NO_MISTAKES`).
- It creates a new attempt on the **same exam**, `kind="mistakes"`, `source_attempt_id` = the finished attempt. Its `question_order` contains only the wrong + skipped questions, shuffled, with MCQ choices reshuffled.
- It works exactly like any other attempt (flashcards, skip, back, feedback, finish, summary).
- It can be repeated on its own result ("retry mistakes of the retry") until nothing is wrong.
- **No LLM calls and no effect on coverage**, since it reuses existing questions.
- An exam's "best score" in lists counts only `full` attempts, so a 3/3 on a retry round does not look like a perfect exam.

---

## 11. Export

Exports are generated **on request** (synchronously, no LLM calls), and they **do not** count items as reviewed.

### 11.1 Printable exam — PDF
`GET /exams/{id}/export?format=pdf&answer_key=end|none` (default `end`)

- **Header:** reviewer title, date, item count, and blank lines for Name and Score.
- **Questions grouped by type, like a school exam:** *Part I – Multiple Choice*, *Part II – True or False*, *Part III – Identification*, each with a one-line instruction. Numbered by `position`. MCQ options are labelled A–D, and Identification has an answer line.
- **Answer key** (`answer_key=end`), on a new page: number → answer, with the short rationale and the source (file, page/slide).
- Filename: `{reviewer-title}-exam-{n}.pdf`.

### 11.2 Study sheet — PDF
`POST /reviewers/{id}/export` with `{ "format": "pdf", "scope"?: {...} }`

- All non-superseded items of the reviewer (or of the scope), grouped **file → topic**, in page order.
- Definitions as **term** — definition. Facts as bullet points. Each line ends with its page/slide number.
- Text is printed **verbatim** from the source items.

### 11.3 Anki CSV
`GET /exams/{id}/export?format=csv` (one card per question) and `POST /reviewers/{id}/export` with `{ "format": "csv", "scope"?: {...} }` (one card per item).

The file starts with Anki's import header lines, so Anki sets everything up automatically:
```
#separator:comma
#html:true
#notetype:Basic
#deck:ARAL::Biology Midterm
#columns:Front,Back,Tags
#tags column:3
```

| Export | Front | Back |
|---|---|---|
| Exam question | prompt (+ choices `A. …<br>B. …` for MCQ) | correct answer `<br><br>` rationale `<br>` *source (file, page)* |
| Reviewer item — `definition` | term | definition `<br>` *source* |
| Reviewer item — `fact` | statement with the key term as `_____` | key term `<br>` *source* |

- **Tags** (space-separated): `aral`, `reviewer::{slug}`, `file::{slug}`, `topic::{slug}`, and `type::{mcq|tf|ident}` for exam exports.
- UTF-8, standard CSV quoting. Field text is HTML-escaped and line breaks become `<br>`.

---

## 12. API reference (v1, prefix `/api/v1`)

All errors use this shape:
```json
{ "error": { "code": "ALL_ITEMS_REVIEWED", "message": "Every item in this reviewer has been part of an exam." } }
```

When `APP_PASSCODE` is set, every route except `/health` needs the header `X-Passcode` (or `?passcode=` on download links); otherwise `401 PASSCODE_REQUIRED` / `PASSCODE_WRONG`.

### Uploads (chunked)
| Method & path | Body | Response |
|---|---|---|
| `POST /uploads` | `{ filename, size, sha256, reviewer_id? }` | `200 { upload_id, chunk_size, chunk_count, duplicate: false }`, or `200 { duplicate: true, document }` when the file is already in the library |
| `PUT /uploads/{id}/chunks/{n}` | raw bytes | `200 { received_chunks, chunk_count }`; `400 BAD_CHUNK` |
| `POST /uploads/{id}/complete` | `{ reviewer_id? }` | `202 document` (status `uploaded`); `409 UPLOAD_INCOMPLETE`; `400 UPLOAD_CORRUPT` |

### Documents (file library)
| Method & path | Body | Response |
|---|---|---|
| `POST /documents` | multipart `file`, optional `reviewer_id` | New file: `202 { id, filename, status, duplicate: false }`. Same file already uploaded: `200 { id, filename, status, duplicate: true }` (§5.5) |
| `POST /documents/{id}/process` | — | Runs one processing step (§5.1) and returns the document with `done`, `busy`, `steps_done`, `steps_total`. Call until `done` |
| `GET /documents` | — | `200 [ { id, filename, file_type, status, page_count, item_count, reviewer_ids, created_at } ]` |
| `GET /documents/{id}` | — | `200 { ...above, error_code?, error_message?, items_by_kind: {definition, fact}, extraction_version, outdated }`. The frontend polls this until `status` is `ready` or `failed`. |
| `POST /documents/{id}/reprocess` | — | `202 { id, status: "extracting" }` (§5.5) |
| `DELETE /documents/{id}` | `?force=true` optional | `204`. If the document is in any reviewer → `409 DOCUMENT_IN_USE` (lists the reviewers) unless `force=true`, which removes it from those reviewers and deletes the exams that contain its items |

### Reviewers
| Method & path | Body | Response |
|---|---|---|
| `POST /reviewers` | `{ "title": "Biology Midterm", "document_ids": ["d1","d2"] }` | `201 reviewer` |
| `GET /reviewers` | — | `200 [ { id, title, document_count, item_count, unused_items, status: "processing" \| "ready" \| "needs_attention", created_at } ]` (`needs_attention` = a document failed) |
| `GET /reviewers/{id}` | — | `200 { id, title, documents: [ { id, filename, status, page_count, item_count } ], item_count, used_items, unused_items, coverage_epoch }` |
| `PATCH /reviewers/{id}` | `{ "title"?: "...", "document_order"?: ["d2","d1"] }` | `200 reviewer` |
| `DELETE /reviewers/{id}` | — | `204` (deletes its exams and attempts; the documents stay in the library) |
| `POST /reviewers/{id}/documents` | `{ "document_id": "d3" }` | `200 reviewer` |
| `DELETE /reviewers/{id}/documents/{document_id}` | — | `200 reviewer`; `409 EMPTY_REVIEWER` if it is the last document |
| `GET /reviewers/{id}/outline` | — | `200 { documents: [ { document_id, filename, page_count, pages: [ { page_no, title, item_count } ] } ], topics: [ { topic, topic_key, item_count, unused_count } ] }` |
| `POST /reviewers/{id}/availability` | `{ "types": [...], "scope"?: {...} }` | `200 { total_items, used_items, unused_items, max_count_for_types, unused_by_type: { mcq, true_false, identification }, unused_outside_scope }` |
| `POST /reviewers/{id}/coverage/reset` | — | `200 { coverage_epoch }` |
| `POST /reviewers/{id}/export` | `{ "format": "pdf" \| "csv", "scope"?: {...} }` | file download (§11.2, §11.3) |

### Exams
| Method & path | Body | Response |
|---|---|---|
| `POST /reviewers/{id}/exams` | `{ "types": ["mcq","true_false"], "count": 20, "scope"?: {...} }` | `202 { id, status: "generating" }`; `409 DOCUMENTS_NOT_READY`; `409 ALL_ITEMS_REVIEWED`; `422 INVALID_SCOPE` |
| `POST /exams/{id}/process` | — | Builds the questions (§8.5) and returns the exam with `done`. Call until `done` |
| `GET /exams/{id}` | — | `200 { id, reviewer_id, status, types, scope, requested_count, actual_count, shortfall }`. No questions are included; they are served one card at a time through attempts. |
| `GET /reviewers/{id}/exams` | — | list of the reviewer's exams with their best (full-attempt) and latest score |
| `POST /exams/{id}/next-set` | `{ "types"?: [...], "count"?: n, "scope"?: {...} \| null }` | `202 { id, status: "generating", parent_exam_id }` or `409 ALL_ITEMS_REVIEWED` |
| `GET /exams/{id}/export?format=pdf&answer_key=end\|none` | — | PDF download (§11.1) |
| `GET /exams/{id}/export?format=csv` | — | CSV download (§11.3) |

Validation: `types` must be non-empty and contain only known values, and `1 ≤ count ≤ MAX_EXAM_ITEMS` (default 100).

### Attempts (flashcards)
| Method & path | Body | Response |
|---|---|---|
| `POST /exams/{id}/attempts` | — | `201 { attempt_id, attempt_no, kind: "full", total, card }` (card 1). This is also **Restart** |
| `GET /attempts/{id}` | — | `200 { attempt_id, kind, status, total, last_viewed_index, progress, cards: [ { index, status: "unanswered" \| "correct" \| "wrong" } ] }` (question map, no content) |
| `GET /attempts/{id}/cards/{index}` | — | `200 card` (1-based index; also updates `last_viewed_index`). Answered cards include `answered: true` + `feedback`. `404` if the index is out of range |
| `POST /attempts/{id}/answer` | `{ "question_id": "...", "response": "c3" }` / `"true"` / `"Photosynthesis"` | `200 { feedback, progress, next_unanswered_index, finished }`; `409 ALREADY_ANSWERED`; `409 ATTEMPT_COMPLETED` |
| `POST /attempts/{id}/finish` | — | `200 summary`. Marks the attempt completed, with skipped cards counted as not correct |
| `GET /attempts/{id}/summary` | — | `200 { kind, correct_count, answered, skipped, total, percent, wrong_cards: [...], skipped_cards: [...], retry_mistakes: { count }, next_set: { unused_items } }`. Each card in the lists contains `prompt`, `your_answer` (null if skipped), `correct_answer`, `why`, `source`. `409 ATTEMPT_NOT_FINISHED` if the attempt is still in progress |
| `POST /attempts/{id}/retry-mistakes` | — | `201 { attempt_id, attempt_no, kind: "mistakes", total, card }`; `409 ATTEMPT_NOT_FINISHED`; `409 NO_MISTAKES` |

**Card**, unanswered (never contains the answer):
```json
{
  "index": 3, "total": 20,
  "answered": false,
  "next_unanswered_index": 4,
  "question": {
    "id": "q_…", "type": "mcq",
    "prompt": "_____ is the process by which green plants use sunlight to synthesize food from carbon dioxide and water.",
    "choices": [ { "id": "c3", "text": "Respiration" }, { "id": "c1", "text": "Photosynthesis" },
                 { "id": "c4", "text": "Transpiration" }, { "id": "c2", "text": "Osmosis" } ]
  }
}
```

**Feedback** (returned by `POST /attempts/{id}/answer`):
```json
{
  "feedback": {
    "is_correct": false,
    "your_answer": { "id": "c3", "text": "Respiration" },
    "correct_answer": { "id": "c1", "text": "Photosynthesis" },
    "why": "Photosynthesis is how plants make their own food using sunlight, carbon dioxide and water.",
    "why_yours_is_wrong": "Respiration refers to the process of breaking down glucose to release energy (Lesson 4.pptx, slide 7).",
    "source": {
      "quote": "Photosynthesis is the process by which green plants use sunlight to synthesize food from carbon dioxide and water.",
      "document_id": "d1", "filename": "Lesson 3 - Photosynthesis.pptx", "page_no": 4
    },
    "changed_span": null,
    "match_note": null
  },
  "progress": { "answered": 3, "unanswered": 17, "total": 20, "correct_count": 2 },
  "next_unanswered_index": 4,
  "finished": false
}
```
When the user goes **back** to an answered card, `GET /attempts/{id}/cards/{index}` returns the same card shape with `"answered": true` and this same `feedback` object, so the frontend can show it exactly as it was shown at the time of answering.
`why_yours_is_wrong` is `null` when the answer is correct, or when there is nothing specific to say (§8.6). `changed_span` is set only for false T/F statements.

---

## 13. Gemini integration (free tier) — `services/llm.py`

All LLM calls go through this one module, so prompts, model, throttling and retries live in one place, and tests can mock it.

### 13.1 Getting a free key (no billing)
1. Sign in to **Google AI Studio** (aistudio.google.com) with a Google account.
2. Create an **API key**. Do **not** set up billing; without it, the project stays on the free tier and can never be charged.
3. Put the key in `.env` as `GEMINI_API_KEY`.

### 13.2 What the free tier means for this app
| Limit | Effect | How the backend handles it |
|---|---|---|
| **Rate limits** (requests per minute and per day). Google does not publish fixed numbers; they are shown per project in AI Studio and can change | A big file, or many files at once, can hit the limit | A throttle in `llm.py` allows one call at a time with a minimum gap (`LLM_MIN_SECONDS_BETWEEN_CALLS`). A `429` is retried with backoff. Extraction saves its progress after every window, so a stopped job **resumes where it left off** instead of starting over |
| **Daily quota used up** | Processing has to wait until the quota resets | The step fails with `LLM_QUOTA_EXCEEDED`. The document/exam shows that error, and **Reprocess** (resume) / generating again later continues from the saved progress. If `GEMINI_FALLBACK_MODEL` is set, the step tries that model first before stopping |
| **Data use:** on the free tier, Google may use the prompts and responses to improve its products, and human reviewers may read them | Lesson text is sent to Google | Fine for normal lesson material. **Don't upload confidential or personal files.** The upload screen should say this |

The app's design already keeps calls low: questions are built from items extracted **once** per file, duplicates are never reprocessed (§5.5), each exam needs only 1–2 calls, and answering, Restart, Retry mistakes and Export need **none**.

### 13.3 Call details
- **SDK / model:** `google-genai`, model `gemini-3.8-flash` (env `GEMINI_MODEL`). Optional `GEMINI_FALLBACK_MODEL` (e.g. `gemini-3.5-flash-lite`, also free) for when the main model is rate-limited. Check the current free models on the Gemini API pricing page before building; the names change often.
- **Structured output:** request JSON with the Pydantic model's schema, then **always** validate it with `Model.model_validate_json(...)`. A response that fails validation is retried once, then that window/batch is marked failed. Nothing parses free-form text by hand.
  ```python
  from google import genai
  from google.genai import types

  client = genai.Client(api_key=settings.gemini_api_key)
  resp = client.models.generate_content(
      model=settings.gemini_model,
      contents=window_text,
      config=types.GenerateContentConfig(
          system_instruction=EXTRACTION_RULES,
          response_mime_type="application/json",
          response_json_schema=ExtractionResult.model_json_schema(),
          temperature=0.2,
      ),
  )
  result = ExtractionResult.model_validate_json(resp.text)
  ```
  (`google-genai` 2.x. The SDK also has a newer Interactions API; `generate_content` is the stable path and is what `llm.py` uses.)
- **Bigger windows, fewer calls:** Gemini Flash takes very long inputs, so extraction windows are ~15 pages (`EXTRACTION_WINDOW_PAGES`) instead of 8. Fewer calls go further under the per-day limit.
- **Blocked / cut-off responses:** if a response is blocked by a safety filter or is cut off before the JSON is complete, split the window or batch in half and retry; if it still fails, mark that part failed and continue with the rest.
- **Errors:** `429` → backoff and retry (then fallback model, then `LLM_QUOTA_EXCEEDED`). 5xx and connection errors → retry with backoff. Other 4xx → fail fast with `LLM_ERROR`.
- **Usage logging:** log the token counts per call with the document/exam id, so you can see how much of the daily quota a file uses.
- **Swappable:** `llm.py` exposes one function, `generate_structured(system, input, schema) -> PydanticModel`. Switching to another provider later (e.g. a local model through Ollama) means changing only this module.
- **Extraction version:** the extraction prompt and rules carry a version constant (`EXTRACTION_VERSION`), which is saved on each document (§5.5).

LLM calls:
| Step | Calls |
|---|---|
| Upload/extraction | ≈ `page_count / 15`, once per unique document. **0** for duplicates (§5.5) |
| Each exam / new set | 1–2 (distractors + falsifications + rationales, batched) |
| Each answer, Restart, Retry mistakes, Export | **0** |

---

## 14. Configuration (`.env.example`)

```
GEMINI_API_KEY=                 # free key from Google AI Studio, no billing
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite   # optional; leave empty to disable
LLM_MIN_SECONDS_BETWEEN_CALLS=6 # throttle for free-tier rate limits
EXTRACTION_WINDOW_PAGES=15
DATABASE_URL=sqlite:///./aral.db
STORAGE_DIR=./storage
MAX_UPLOAD_MB=25
MAX_EXAM_ITEMS=100
IDENT_FUZZY_THRESHOLD=90
SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe   # needed for .ppt only
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
UPLOAD_CHUNK_MB=3               # browser upload chunk size
STEP_CLAIM_SECONDS=280          # how long one processing step may hold a document / exam
APP_PASSCODE=                   # optional; set it when the app is online (docs/DEPLOYMENT.md)
```

On Vercel, `DATABASE_URL` must point at a PostgreSQL database (`postgresql://…`); see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## 15. Testing

- **Ingestion:** fixture PDF/PPTX/PPT → expected page count, slide titles, bullet indentation, table rows, hyphen joining, header/footer removal.
- **Duplicates:** the same bytes return the existing id with `duplicate: true` and make no Gemini calls; a duplicate upload with `reviewer_id` adds it to the reviewer once; a failed duplicate is re-extracted; the same text in a different file copies the items with no Gemini calls; reprocess supersedes the old items and old exams still render.
- **Fidelity:** unit tests for every row of the §9 table, including the negative cases (a paraphrased quote is snapped or dropped; a false statement with two edits is rejected).
- **Reviewers & scope:** an exam draws from all of the reviewer's documents; `DOCUMENTS_NOT_READY`; adding a document after exams exist makes its items unused; removing one stops it being selected; scope by document, page range, topic, and both combined; `INVALID_SCOPE`; topic grouping of "(cont.)" titles; a new set inherits the scope, and an explicit `null` widens it.
- **Selector:** never returns used items; spreads items across documents and pages; redistributes the shortfall; `409` with `unused_outside_scope` when nothing is left; a coverage reset makes items available again.
- **Grading:** Identification normalization, aliases, typo tolerance, and the threshold edge.
- **Feedback:** each type returns the correct `why` / `why_yours_is_wrong`; an Identification answer that matches another term in the reviewer returns that term's meaning; a bad rationale falls back to the template.
- **Flashcard rules:** an unanswered card never contains its answer; going back to an answered card returns its saved feedback; `ALREADY_ANSWERED` is enforced; skipping leaves a card unanswered; `next_unanswered_index` wraps around to earlier skipped cards; the attempt auto-completes on the last unanswered card; Finish with skipped cards scores them as not correct; resuming opens `last_viewed_index`.
- **Retry mistakes:** contains exactly the wrong + skipped cards; `NO_MISTAKES` / `ATTEMPT_NOT_FINISHED`; it can be chained; it does not change coverage; it does not count toward the best score.
- **Export:** the PDF opens and has the right parts and answer key; non-ASCII text renders; the CSV header lines are correct; HTML is escaped; the tags are correct; a sample CSV imports into Anki (manual check once).
- **API:** the full flow with a mocked `llm.py`: upload 2 files (one a duplicate) → create a reviewer → poll → outline → availability → create an exam (with and without scope) → attempt → answer / skip / go back → finish → summary → retry mistakes → restart → next-set → … → `ALL_ITEMS_REVIEWED` → reset → export.
- **Prompt check (manual, against real Gemini):** 3–5 real lesson files. Read the extracted items and check that the quotes are verbatim and that the T/F edits are actually false.

---

## 16. Build order

1. ✅ Project skeleton, config, DB models + Alembic migration, health endpoint
2. ✅ Upload + PDF/PPTX extraction + `document_pages` + same-file duplicate check
3. ✅ `llm.py` + source-item extraction + fidelity validation + same-text duplicate check + reprocess
4. ✅ Reviewers (combining files) + outline + scope + selector + Identification + exams API
5. ✅ Flashcard attempts: cards by index (skip / back), question map, answer + immediate grading, feedback, finish, summary
6. ✅ True/False falsification + MCQ distractors + rationales (§8.6)
7. ✅ Restart / Retry mistakes / next-set / coverage reset + availability endpoint
8. ✅ Export: printable exam PDF, study sheet PDF, Anki CSV
9. ✅ `.ppt` conversion, error codes, usage logging
10. Frontend: designed in [FRONTEND.md](FRONTEND.md); to be built next

Status: built in `backend/` (see [backend/README.md](backend/README.md)); 43 automated tests pass with a fake Gemini, and a live run against the real Gemini on two sample lessons works end to end.

---

## 17. Open questions

1. Should speaker notes in PowerPoint count as lesson material?
2. Is OCR for scanned PDFs needed later?
3. Should Identification accept close spellings (typo tolerance, currently on), or require an exact answer?
4. Should a "new set" exclude items per question type instead (e.g. an item used as T/F can still appear as Identification)? Currently, an item used in any exam of the reviewer is excluded from the next set entirely.
