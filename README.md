# ARAL

**Turn lesson files into exam-style reviewers.**

ARAL reads your lesson PDFs and PowerPoint slides and builds flashcard exams from them: multiple choice,
true or false, and identification. Every question uses the lesson's own wording, so you study exactly
what your teacher wrote.

---

## Concept

### The problem
Making a reviewer by hand takes hours, and general AI quiz tools reword the material. The questions
end up sounding different from the lesson, and sometimes they're simply wrong.

### How ARAL works

```
 Lesson files ──► Extract ──► Facts bank ──► Exam ──► Flashcards ──► Results
 (PDF / PPTX)     (once)      (verbatim)     (pick N)  (one at a time)  (retry / new set)
```

1. **Upload** one or more lesson files and group them into a **reviewer** (e.g. *Biology Midterm* = Lessons 1–4).
2. **Extract once.** Each file is read a single time. Definitions and key facts are pulled out **word for word**,
   and every quote is checked against the original page. A file uploaded again is reused, not reprocessed.
3. **Build an exam.** Pick the question types, how many items, and optionally which slides or topics.
4. **Answer flashcards** one at a time. After each answer you see right or wrong, a short reason, and the
   exact line from the lesson it came from. You can skip and go back, but answers can't be changed.
5. **Keep going.** *Retry mistakes*, *Restart* the same set, or make a *New set* from material you haven't
   seen yet. ARAL tracks which items each reviewer has already covered.

### Question types

| Type | What you see | Built from |
|---|---|---|
| **Multiple choice** | A sentence from the lesson with a blank, or "which best describes…" | The lesson sentence; wrong options are other terms from the same lesson |
| **True or false** | A lesson sentence, either exact or with one detail changed | Exactly one word or phrase is swapped, and the feedback shows what changed |
| **Identification** | A definition from the lesson | You type the term; small typos are accepted |

### Principles
- **Faithful to the source.** Questions are assembled from verbatim lesson text, never paraphrased.
- **Few AI calls.** About one call per file and one per exam. Answering, retrying and exporting cost none.
- **Private by default.** Runs on your own computer with a local database.
- **Exportable.** Printable exam (PDF, with answer key), study sheet (PDF), and Anki flashcards (CSV).

---

## Tech stack

### Frontend
| | |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| Routing | React Router |
| Server state | TanStack Query (caching, polling while files process) |
| Styling | Plain CSS with design tokens; black and white, light and dark mode |
| Fonts | VT323 (display), IBM Plex Mono (body), self-hosted |

### Backend
| | |
|---|---|
| Language / framework | Python 3.11+ / FastAPI |
| Database | SQLite through SQLAlchemy 2, migrations with Alembic (PostgreSQL-ready) |
| PDF reading | PyMuPDF |
| PowerPoint reading | python-pptx (old `.ppt` converted with LibreOffice) |
| Text matching | RapidFuzz (quote checks, answer grading) |
| AI | Google Gemini API, free tier (`google-genai`), structured JSON output |
| Exports | fpdf2 (PDF), Python `csv` (Anki) |
| Tests | pytest with a fake Gemini, plus a Playwright end-to-end run |
