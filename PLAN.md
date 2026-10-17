# Plan: agent rules, the summary card, shared CSS

Status: draft for discussion. No code has changed yet, except step 0.

## 0. Revert the `.md` viewer: done

`4f272a9` reverts `faf9058` (the `.md` rendering in `html_server.py`, plus its notes in `PAGES.md`
and the tutorial `index.html`). It is pushed to `claude/friendly-newton-vty0yd`. The tree is now
byte-identical to `e884a84`.

---

## 1. Rename `PAGES.md` → `AGENT_RULE.md`

The file is the rule book every page agent gets. The new name says so.

| Where | Change |
|---|---|
| `PAGES.md` | `git mv` to `AGENT_RULE.md`; retitle it "Rules for page agents" |
| `review.py:35` | `PAGES_MD` → `AGENT_RULE_MD`, pointing at `AGENT_RULE.md` (also `pages_md_path` in `SYSTEM_PROMPT`) |
| `bin/DirAI:27-29` | link `~/.config/dirai/AGENT_RULE.md`; import `@~/.config/dirai/AGENT_RULE.md` |
| `bin/DirAI` init | the existing `OLD_IMPORT` rewrite becomes a list: `@~/DirAI/PAGES.md` and `@~/.config/dirai/PAGES.md` are both rewritten to the new line |
| `bin/DirAI` start | also keep `~/.config/dirai/PAGES.md` as a link to the new file, so trees not yet re-run keep working |
| `dirai_config.py`, `README.md`, tutorial `index.html` | update the name |

**Migration for you:** run `DirAI start` (or `restart`) once per tree. Nothing else is needed.

---

## 2. One `index.html` with a summary card that tools can read

### 2a. Card format

Every page has this block near the top. The markers make it extractable with `sed`, or with the
parser below, without reading the rest of the page.

```html
<!-- dirai:card -->
<section id="dirai-card">
  <dl>
    <dt>Objective</dt> <dd>What this page answers.</dd>
    <dt>Inputs</dt>    <dd>Data/folders/scripts it starts from.</dd>
    <dt>Outputs</dt>   <dd>Files it produces (figures, results).</dd>
    <dt>Result</dt>    <dd>Current answer, numbers with units and uncertainty.</dd>
    <dt>Open</dt>      <dd>What is unfinished or running (job ids).</dd>
    <dt>Updated</dt>   <dd>2026-10-17</dd>
  </dl>
  <script type="application/json" id="dirai-results">{"rate": 3.2e-3, "rate_err": 4e-4}</script>
</section>
<!-- /dirai:card -->
```

- **Required:** Objective, Result, Updated. Inputs, Outputs and Open are recommended.
- **`dirai-results` JSON:** optional, and must parse if present. It holds the numbers other pages
  or scripts use.
- **Visible:** humans see the card at the top of the page, styled by `page.css` (step 3).

### 2b. Parser: `dirai_card.py` (new, stdlib only)

- `extract(path)` → `{"objective": …, "result": …, "updated": …, "results": {…}}`, or None.
- `problems(path)` → a list of what's wrong: missing markers, a missing required field, invalid
  JSON, `Updated` not changed after an edit.
- **CLI:** `python3 dirai_card.py <page folder>…` prints each card as short text. Agents use this to
  read other pages cheaply (a few hundred tokens instead of about 30k). It goes on the default
  allow list in `review.py`.
- The same functions serve the server checks (2c) and later work (the list page, fan-in to a
  lead page).

### 2c. Enforcement: making every agent keep the card

Four layers, from soft to hard:

1. **Rule.** `AGENT_RULE.md` gets a "Summary card" section: the exact template, the required fields,
   "update it at the end of every run that changes the page", and "to learn about another page, run
   `dirai_card.py`, don't read its index.html".
2. **Template.** `STARTER_PAGE` (`review.py:183`, the page New agent creates) already contains the
   card with the Objective filled from the task. New pages start in the right format.
3. **Server check after each run, with a fix in the same session.** In `_drive()`
   (`review.py:1091`), on the run's `result` message: if `index.html` changed during the run and
   `problems()` is non-empty, send one more user message over the still-open stream-json stdin
   (`live.send`). The message: *"The summary card is missing/invalid: <problems>. Fix only the card."*
   Then keep reading until the next `result`.
   - It runs in the same session, so the context is cached and the fix is cheap.
   - At most one retry per run. A second failure goes to step 4.
   - Runs that didn't edit the page aren't checked, so read-only questions are never nagged.
4. **Visible state.** The panel shows "Card: missing (Objective, Result)" and the list page gets a
   ✓/✗ card column. You see at a glance which pages are out of format.

**Existing pages:** no sweep. They're checked the first time a run edits them, and that run gets
the follow-up in layer 3. Pages migrate as they're touched, at no extra cost.

**Rejected: Claude Code hooks** (a Stop hook that refuses to stop until the card is valid). Runs
use `--restricted`, which ignores settings files, so hooks would need `--settings` passed per run.
Layer 3 does the same thing with code we control.

---

## 3. Shared CSS: `page.css`

- **The file:** `page.css` in the DirAI checkout. It contains the house style (from the tutorial
  `index.html`), a dark mode, the card style, and a few classes for agents: `.note`, `.warn`,
  `figure` + `figcaption` (for the "Script: …" caption), and `.tbl` (a table that scrolls
  sideways).
- **Served** at `/_dirai/page.css` to every visitor. `/_review/` is owner-only, so it can't live
  there.
- **Injected** by `send_page()` (`html_server.py`) as the first element in `<head>`:
  `<link rel="stylesheet" href="/_dirai/page.css">`.
  - **Only into pages without their own `<style>`.** Existing styled pages are untouched, so
    nothing that works today changes look. When an agent next rewrites a page without a
    `<style>`, the page picks up the shared style.
  - The list page `www/index.html` is not changed.
- **Rule in `AGENT_RULE.md`:** "Don't write `<style>` or inline `style=`. Use plain HTML and these
  classes: …"
- **`STARTER_PAGE`:** drop its `<style>` line.
- **Check:** `page.css` must not restyle the injected panel, Home button or status bar. Scope the
  general rules (`body`, `table`, `h2` …) so the panel's own elements are unaffected, and test
  with the panel open.
- **GitHub Pages:** out of scope. Published pages without a `<style>` show plain HTML.

---

## Order, commits, tests

| # | Commit | Test |
|---|---|---|
| 1 | Rename to `AGENT_RULE.md` | `DirAI init` on a scratch tree with an old import line → rewritten; the run prompt contains the rules |
| 2 | `page.css` + injection | Scratch tree: a page without `<style>` gets the link, a page with one does not; screenshot both with the panel open |
| 3 | Card: rule, starter page, `dirai_card.py`, follow-up check, panel/list display | Unit tests for `extract`/`problems`. A fake `claude` (via `REVIEW_CLAUDE_CMD`) that edits the page without the card → the server sends exactly one follow-up |

Each is a separate commit pushed to `claude/friendly-newton-vty0yd`. No PR unless you ask.

---

## Open questions

1. **Card fields:** are Objective / Inputs / Outputs / Result / Open / Updated the right set? Do you
   want e.g. "Method" or "Next step"?
2. **Required:** only Objective + Result + Updated, or all six?
3. **Placement:** card always visible at the top, or inside a collapsible `<details>` (open by
   default)?
4. **Follow-up retry (2c layer 3):** is one automatic fix per run right, or should the server only
   flag the problem (layer 4) and leave the fix to you?
5. **CSS on existing styled pages:** keep "inject only when the page has no `<style>`", or inject
   everywhere and let page styles override?
6. **The tutorial `index.html` in this repo:** convert it to `page.css` + a card as the worked
   example, or leave it as is?
