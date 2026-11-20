"""Draw docs/overview.svg, the "How it works" schematic in README.md.
Run: python3 ~/DirAI/docs/overview.py"""
import os

W, H = 960, 520
out = []
add = out.append


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, fill, stroke, title, sub=None):
    add('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="%s" stroke="%s" stroke-width="1.5"/>'
        % (x, y, w, h, fill, stroke))
    add('<text x="%d" y="%d" class="t" fill="%s">%s</text>' % (x + 12, y + 22, stroke, esc(title)))
    if sub:
        add('<text x="%d" y="%d" class="s">%s</text>' % (x + 12, y + 38, esc(sub)))


def text(x, y, s, cls="b", anchor="start", fill=None):
    if s.startswith(" "):   # SVG drops leading spaces: indent a continuation line by moving it
        x, s = x + 9, s.strip()
    add('<text x="%d" y="%d" class="%s" text-anchor="%s"%s>%s</text>'
        % (x, y, cls, anchor, ' fill="%s"' % fill if fill else "", esc(s)))


def arrow(x1, y1, x2, y2, dashed=False):
    add('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#333" stroke-width="1.6" marker-end="url(#ah)"%s/>'
        % (x1, y1, x2, y2, ' stroke-dasharray="5 4"' if dashed else ""))


def step(x, y, n, lines, anchor="middle"):
    """A numbered label: a dark circle with the step number, then its text lines below it."""
    add('<circle cx="%d" cy="%d" r="9" fill="#333"/>' % (x, y))
    text(x, y + 4, str(n), "n", "middle", "#fff")
    for i, s in enumerate(lines):
        text(x, y + 24 + 14 * i, s, "l", anchor)


add('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
    'font-family="Helvetica, Arial, sans-serif">' % (W, H, W, H))
add('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker>'
    '<style>.t{font-size:15px;font-weight:bold}.s{font-size:11px;fill:#666}.b{font-size:12px;fill:#222}'
    '.l{font-size:11px;fill:#333}.n{font-size:11px;font-weight:bold}.m{font-size:12px;font-family:monospace;fill:#222}'
    '.c{font-size:11px;fill:#8a6d1f}</style></defs>')
add('<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H))
text(W // 2, 30, "DirAI: every folder with an index.html is an agent you chat with in the browser", "t", "middle", "#222")

# ---- browser (top left)
box(20, 50, 280, 270, "#eef4fb", "#3d6fae", "Your browser", "http://127.0.0.1:<port>")
# agent list
add('<rect x="34" y="98" width="252" height="86" rx="5" fill="#fff" stroke="#9db6d6"/>')
text(44, 116, "Agent list  (www/index.html)", "b")
for i, (name, state, col) in enumerate([("projA", "done", "#3f8f5a"), ("projA/fit", "running", "#d08a00"),
                                         ("projB", "needs you", "#c0392b")]):
    y = 136 + 18 * i
    add('<circle cx="50" cy="%d" r="4" fill="%s"/>' % (y - 4, col))
    text(60, y, name, "m")
    text(276, y, state, "l", "end")
# agent page
add('<rect x="34" y="194" width="252" height="114" rx="5" fill="#fff" stroke="#9db6d6"/>')
text(44, 212, "Agent page  (projA/index.html)", "b")
add('<rect x="44" y="220" width="140" height="34" rx="3" fill="#f4f4f4" stroke="#ccc"/>')
text(50, 234, "Summary card", "l")
text(50, 248, "Objective · Result · Open", "s")
add('<rect x="44" y="260" width="140" height="10" fill="#fff3a8"/>')
add('<rect x="44" y="276" width="140" height="8" fill="#eee"/>')
add('<rect x="44" y="290" width="100" height="8" fill="#eee"/>')
text(114, 268, "changed: yellow", "s", "middle")
# chat panel
add('<rect x="194" y="220" width="84" height="80" rx="3" fill="#f7f9fc" stroke="#9db6d6"/>')
text(200, 234, "Chat", "l")
add('<rect x="214" y="240" width="58" height="12" rx="6" fill="#d7e5f7"/>')
add('<rect x="200" y="256" width="58" height="12" rx="6" fill="#e9e9e9"/>')
add('<rect x="200" y="276" width="72" height="16" rx="2" fill="#fff" stroke="#bbb"/>')
text(204, 288, "Enter = send", "s")

# ---- server (top middle)
box(390, 50, 240, 250, "#f4effb", "#6f4fae", "DirAI server", "one per tree · port in www/dirai.json")
for i, s in enumerate(["serves pages (owner key login)", "builds the agent list",
                       "queues runs, 5 at a time", "pauses at your usage levels",
                       "sends scheduled messages", "  (once / daily / weekly / hourly)",
                       "waits for the runs' SLURM jobs", "asks you about blocked actions"]):
    text(404, 112 + 22 * i, s if s.startswith(" ") else "• " + s, "b")

# ---- tree (right, full height)
box(700, 50, 240, 450, "#fbf6ea", "#a07a1c", "The tree", "a git repo or any folder DirAI start serves")
rows = [(0, "my-repo/", ""), (1, "CLAUDE.md", "imports agent rules"), (1, "projA/", ""),
        (2, "index.html", "agent"), (2, "fit.py  fit.png", ""), (2, "fit/", ""),
        (3, "index.html", "agent"), (1, "projB/", ""), (2, "index.html", "agent"),
        (1, "notes/", "not an agent"), (1, "www/", "generated, gitignored"),
        (2, "index.html", "agent list"), (2, "agents.json", "chat threads"),
        (2, "dirai.json", "port, settings")]
for i, (lvl, name, note) in enumerate(rows):
    y = 108 + 27 * i
    x = 716 + 18 * lvl
    agent = note == "agent"
    if agent:
        add('<rect x="%d" y="%d" width="78" height="18" rx="3" fill="#e3f1e7" stroke="#3f8f5a"/>' % (x - 4, y - 13))
    text(x, y, name, "m")
    if note:
        text(930, y, note, "c", "end")

# ---- run (bottom middle)
box(390, 370, 240, 130, "#eef8f0", "#2f7d4a", "A Claude Code run", "claude -p, in the agent's folder")
for i, s in enumerate(["• reads index.html + your message", "• edits index.html, reruns scripts",
                       "• may edit only its own folder", "• replies in 3 short lines"]):
    text(404, 426 + 18 * i, s, "b")

# ---- SLURM (bottom left)
box(20, 370, 280, 130, "#f3f3f3", "#555", "SLURM", "for long or heavy work")
for i, s in enumerate(["• jobs the run submitted with sbatch", "• checked with sacct every 10 min",
                       "   (no tokens used while waiting)", "• when all finish: a new run gets", "   their results"]):
    text(34, 426 + 16 * i, s, "b")

# ---- arrows and numbered steps
arrow(300, 120, 390, 120)
step(345, 138, 1, ["you send", "a message"])
arrow(510, 300, 510, 370)
step(535, 330, 2, ["starts a run"], "start")
arrow(630, 435, 700, 435)
step(665, 380, 3, ["edits", "index.html"])
arrow(390, 470, 300, 470)
step(345, 428, 4, ["sbatch"])
arrow(240, 370, 400, 300, dashed=True)
step(300, 350, 5, [])
text(318, 352, "jobs done", "l")
arrow(390, 250, 300, 250)
step(345, 268, 6, ["reply + yellow", "changes"])
arrow(630, 175, 700, 175)
text(665, 166, "finds agents", "l", "middle")

add("</svg>")
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overview.svg")
with open(path, "w") as f:
    f.write("\n".join(out) + "\n")
print("wrote", path)
