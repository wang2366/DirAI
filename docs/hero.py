"""Draw hero.svg: the proposed README hero picture. A lab workstation and an HPC cluster (each drawn
with an icon, each folder an agent) link over ssh to your laptop, whose browser shows one agent list
with every machine's agents, the laptop's own included.
Run: python3 ~/DirAI/docs/hero.py"""
import os

W, H = 900, 420
o = []


def t(x, y, s, size=13, fill="#222", anchor="start", bold=False, mono=False):
    o.append('<text x="%d" y="%d" font-size="%d" fill="%s" text-anchor="%s"%s%s>%s</text>' % (
        x, y, size, fill, anchor, ' font-weight="bold"' if bold else "",
        ' font-family="monospace"' if mono else "", s.replace("&", "&amp;").replace("<", "&lt;")))


def rect(x, y, w, h, fill, stroke, r=10, sw=1.5):
    o.append('<rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s" stroke="%s" stroke-width="%s"/>'
             % (x, y, w, h, r, fill, stroke, sw))


def dot(x, y, r, fill):
    o.append('<circle cx="%d" cy="%d" r="%s" fill="%s"/>' % (x, y, r, fill))


def workstation(x, y, col):
    """a desktop: monitor on a stand, and a tower beside it (about 70 x 56)"""
    rect(x, y, 46, 32, "#fff", col, 3, 2)           # monitor
    rect(x + 5, y + 5, 36, 22, "#e9e3f5", "none", 1, 0)   # its screen
    rect(x + 20, y + 32, 6, 9, col, "none", 0, 0)    # stand
    rect(x + 11, y + 41, 24, 4, col, "none", 2, 0)   # foot
    rect(x + 52, y + 4, 18, 41, "#fff", col, 3, 2)   # tower
    for k in range(2):
        rect(x + 56, y + 10 + 6 * k, 10, 2, col, "none", 1, 0)
    dot(x + 61, y + 36, 2.5, "#3f8f5a")              # power light


def cluster(x, y, col):
    """two server racks, four units each with a status light (about 66 x 56)"""
    for r in range(2):
        rx = x + 34 * r
        rect(rx, y, 30, 52, "#fff", col, 3, 2)
        for u in range(4):
            uy = y + 5 + 11.5 * u
            o.append('<rect x="%d" y="%.1f" width="22" height="8" rx="1.5" fill="#e3efe6" stroke="%s" '
                     'stroke-width="1"/>' % (rx + 4, uy, col))
            dot(rx + 21, uy + 4, 1.8, "#3f8f5a" if (u + r) % 3 else "#d08a00")
            o.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                     % (rx + 7, uy + 4, rx + 16, uy + 4, col))


o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica, Arial, sans-serif">' % (W, H, W, H))
o.append('<rect width="%d" height="%d" fill="#fff"/>' % (W, H))
t(W // 2, 34, "Every folder is an agent. Every machine, one list.", 20, "#222", "middle", True)

DOT = {"working": "#d08a00", "done": "#3f8f5a", "waits on jobs": "#3d6fae", "needs you": "#c0392b"}
remotes = [("Lab workstation", "#6f4fae", workstation, [("~/data/cleanup/", "working"), ("~/data/plots/", "done")]),
           ("HPC cluster", "#2f7d4a", cluster, [("/scratch/sim/", "waits on jobs"), ("/scratch/fit/", "working")])]

# the remote machines on the left, each with its icon and its folder-agents
for i, (name, col, icon, agents) in enumerate(remotes):
    y = 72 + 150 * i
    rect(24, y, 360, 130, "#fafafa", col)
    t(40, y + 24, name, 15, col, bold=True)
    icon(40, y + 46, col)
    for j, (folder, state) in enumerate(agents):
        yy = y + 42 + 34 * j
        rect(124, yy, 246, 26, "#fff", "#ccc", 4)
        t(132, yy + 17, folder, 12, "#222", mono=True)
        dot(256, yy + 13, 5, DOT[state])
        t(266, yy + 17, state, 11, "#555")
    t(124, y + 118, "each folder with an index.html is an agent", 11, "#888")
    # its ssh link into the laptop
    o.append('<line x1="384" y1="%d" x2="458" y2="%d" stroke="%s" stroke-width="2" stroke-dasharray="6 4"/>'
             % (y + 65, 200 + 30 * i, col))
t(421, 196, "ssh", 12, "#777", "middle")

# your laptop on the right: its screen is the browser, showing the one agent list
LC = "#3d6fae"
rect(458, 62, 420, 300, "#2b2f36", "#2b2f36", 12)                  # lid and bezel
rect(470, 74, 396, 276, "#fff", "none", 3, 0)                       # screen
rect(470, 74, 396, 22, "#e8ecf1", "none", 3, 0)                     # browser bar
for k, c in enumerate(("#e06c5f", "#e3b341", "#5fb36a")):
    dot(482 + 12 * k, 85, 4, c)
rect(526, 78, 330, 14, "#fff", "#cfd6df", 7, 1)
t(536, 89, "127.0.0.1:8765 · DirAI agent list", 10, "#666")
o.append('<polygon points="436,362 900,362 884,382 452,382" fill="#c9ced6" stroke="#9aa3ae" stroke-width="1"/>')
rect(640, 362, 56, 6, "#9aa3ae", "none", 3, 0)                      # thumb notch
dot(668, 68, 2, "#555")                                              # camera

rows = [("laptop", "~/paper/", "done"), ("laptop", "~/talk/", "needs you"), ("lab", "~/data/cleanup/", "working"),
        ("lab", "~/data/plots/", "done"), ("cluster", "/scratch/sim/", "waits on jobs"),
        ("cluster", "/scratch/fit/", "working")]
for i, (m, folder, state) in enumerate(rows):
    y = 106 + 31 * i
    rect(482, y, 372, 26, "#fff", "#c6d6ea", 4)
    dot(496, y + 13, 5, DOT[state])
    t(508, y + 17, "%s:%s" % (m, folder), 12, "#222", mono=True)
    t(846, y + 17, state, 11, "#555", "end")
t(668, 314, "Click a row: its report + a chat with that agent.", 12, "#333", "middle")
t(668, 332, "It keeps working after you close the tab.", 12, "#333", "middle")
t(668, 404, "Your laptop: the browser is the list", 14, LC, "middle", True)
o.append("</svg>")

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero.svg")
open(path, "w", encoding="utf-8").write("\n".join(o) + "\n")
print("wrote", path)
