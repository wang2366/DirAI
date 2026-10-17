# Rules for page agents

For trees served by DirAI (a git repo where `DirAI` was run at the top): results and write-ups
are HTML pages, one per folder, `<folder>/index.html`, anywhere in the tree. DirAI serves them
and lists every one on the tree's `www/index.html`.

To apply these rules to every Claude session in the tree, the tree's root `CLAUDE.md` has the
line  `@~/.config/dirai/AGENT_RULE.md`  (`DirAI init` adds it; that path is a link DirAI keeps pointing
at this file; chat-with-Claude runs started from a page get them directly).

- **Every page starts with a summary card**, right under its `<h1>`, in exactly this form:

  ```html
  <!-- dirai:card -->
  <details id="dirai-card" open>
    <summary>Summary</summary>
    <dl>
      <dt>Objective</dt> <dd>What this page answers.</dd>
      <dt>Inputs</dt>    <dd>Data, folders and scripts it starts from.</dd>
      <dt>Outputs</dt>   <dd>Files it produces (figures, results).</dd>
      <dt>Result</dt>    <dd>The current answer: numbers with units and uncertainty.</dd>
      <dt>Open</dt>      <dd>What is unfinished or still running (job ids).</dd>
      <dt>Updated</dt>   <dd>YYYY-MM-DD</dd>
    </dl>
    <script type="application/json" id="dirai-results">{"name": value, ...}</script>
  </details>
  <!-- /dirai:card -->
  ```

  All six fields are required; write `none` when nothing applies. Whenever you change the page,
  update the card to match and set Updated to today. The `dirai-results` JSON is optional: put the
  page's key numbers there when other pages or scripts may use them, and it must be valid JSON.
  The server checks the card after every run that changes the page, and asks you to fix it if not.
  To learn what another page found, run `dirai_card.py` on its folder (path given in your
  instructions) rather than reading its whole `index.html`.
- **Every figure names its plotting script.** Put a caption or line next to each image with the
  path to the script that makes it, relative to the page's folder, e.g.
  `Script: analysis/plot_rate.sh`. Where possible, name the script after the plot
  (`foo.png` made by `foo.sh` / `foo.py`).
- **Keep `todo.md` current.** Each page folder can have a `todo.md`, one item per line:
  `- [ ] open item` / `- [x] done item`. The server shows the open items, and the SLURM jobs
  running in that folder, in a status bar at the top of the page. When you finish an item, tick
  it; when work leaves something open (a job still running, a next step), add it.
- **Jobs that run elsewhere go in `job_dirs.txt`.** The status bar (and the server's wait for a
  page's jobs) counts the jobs whose working directory is in the page folder. When the page's
  work runs jobs in other folders, e.g. a test sweep in another checkout, put those folders in
  the page folder's `job_dirs.txt`, one absolute path per line.
- Reference images and other files by relative path inside the tree; the server only serves
  `.html` and image files (`.png .jpg .jpeg .gif .svg .webp`).
- Don't add your own "Home"/back-to-list link: the server adds a Home button to every page.
- **No CSS in pages.** Don't write a `<style>` block or `style=` attributes: the server links the
  shared `page.css` into every page without a `<style>`. Use plain HTML and its classes:
  `<div class="note">` (or `class="note warn"`) for callouts, `<div class="tbl">` around a wide
  table, `<figure>` + `<figcaption>` for a figure and its "Script: …" line, `<p class="lede">` for
  the line under the title. When you edit a page that has its own `<style>`, remove it if the page
  reads fine without it.
- Write absolute paths without `..` in commands.
