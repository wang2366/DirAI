# HTML page conventions

For trees served by DirAI (a git repo where `DirAI` was run at the top): results and write-ups
are HTML pages, one per folder, `<folder>/index.html`, anywhere in the tree. DirAI serves them
and lists every one on the tree's `www/index.html`.

To apply these rules to every Claude session in the tree, the tree's root `CLAUDE.md` has the
line  `@~/.config/dirai/PAGES.md`  (`DirAI init` adds it; that path is a link DirAI keeps pointing
at this file; chat-with-Claude runs started from a page get them directly).

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
  `.html` and image files (`.png .jpg .jpeg .gif .svg .webp`), plus `.md` files to the owner,
  rendered in the browser (`$...$`/`$$...$$` math with KaTeX, ```` ```mermaid ```` diagrams).
  The page itself stays `index.html`; a `.md` copy is for reading, not a replacement.
- Don't add your own "Home"/back-to-list link: the server adds a Home button to every page.
- Write absolute paths without `..` in commands.
