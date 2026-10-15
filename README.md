# DirAI

Serve any git repo as browsable HTML pages, with a Claude Code assistant on every page.

Each page folder holds an `index.html`. DirAI lists them on the repo's
`www/index.html`. The owner gets an assistant panel on each page: a comment there starts a
background `claude -p` session in that folder, which edits the page, reruns scripts or submits
jobs, then replies in the thread. The parts of the page its latest edit added or changed are
highlighted (compared with a copy saved before the run, in `www/page_prev/`).

If a run leaves SLURM jobs in the queue (ones it submitted, or any of yours running in the page
folder), the page stays "working" while the server checks the queue (`sacct`) every 10 minutes, which
costs no tokens. When the jobs have all left the queue, the server sends the assistant their `sacct`
results so it can update the page. A comment can still go in while the page waits. Five automatic
messages in a row is the limit, until you comment again.

## Setup (once per machine)

```bash
git clone <this repo> <anywhere>/DirAI
ln -s <anywhere>/DirAI/bin/DirAI ~/.local/bin/DirAI      # any folder on your PATH
```

The checkout can live anywhere. `DirAI init` and `DirAI start` keep `~/.config/dirai/PAGES.md`
linked to it, and a tree's `CLAUDE.md` imports the page rules from there, so the committed import
line works on every machine. After moving the checkout, update the PATH link and run `DirAI start`
(or `init`) once to repoint it.

Needs Python 3.6+, `git`, `curl`, and Claude Code (`~/.local/bin/claude`, or set `REVIEW_CLAUDE_CMD`).

## Use (per repo)

```bash
cd <your repo>        # anywhere inside it
DirAI init            # www/dirai.json (port), .gitignore lines, CLAUDE.md import of the page rules
DirAI start           # on this machine; or: DirAI start NODE | --job (its own sbatch job)
DirAI status | restart | stop | build | list
```

Each repo (each clone, even of the same repo) runs its own server on its own port, so trees start
and stop independently. `DirAI list` shows them all.

Opening a page as the owner: connect through an SSH tunnel to the node, then visit
`/_review/login?key=<~/.config/dirai/key>` once to set the owner cookie.

## Where things live

| Where | What |
|---|---|
| this repo | the tool: server, list builder, assistant (`review.py`), panel scripts, `PAGES.md` page rules |
| `<repo>/www/` | per tree, generated and gitignored: list page, threads (`reviews.json`), caches, `server_host.txt`, logs, and `dirai.json` settings |
| `~/.config/dirai/` | per user: owner key, "Always allow" grants, shared Claude usage reading, the list of trees, and `PAGES.md` (a link to this checkout's page rules) |

`www/dirai.json`:

```json
{"port": 8765,
 "read_dirs": ["/data/shared"],              "allow": ["Bash(~/tools/run.sh:*)"],
 "slurm": ["-A", "mygroup", "-p", "cpu"]}
```

`read_dirs`: extra folders page assistants may read (the repo itself always). `allow`: extra
Claude Code permission rules for them. `slurm`: extra `sbatch` options for `DirAI start --job`.

## Assistant safety

Runs use `claude -p --restricted` with an allow list (`review.py`): reads only inside the page's
own area (its nearest git repo, or its own folder outside any repo; the tree's top page sees the
whole tree) and `read_dirs`. To let a page read another folder of the tree, name the path in your
comment (granted for that page automatically) or click Allow when a read is blocked; folder reads
stay with that page even under "Always allow". Scripts the assistant runs (`python3 x.py`) are not
confined by this, only Claude's own file tools and simple shell commands; edits only in the page's folder, deletions only through `page_rm.sh`, destructive git
commands always denied. Blocked actions show in the panel with "Allow once" / "Always allow".
New tasks pause at 95 % of Claude's 5-hour limit or 98 % of the weekly limit and resume after the
reset (`claude_usage.py`).
