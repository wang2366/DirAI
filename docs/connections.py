"""Draw connections.svg: a mock-up of the agent list's Machines map and of an agent's panel with its Schedule
editor, drawn after the UI code (web/agent_list.js: machineBox, treeNode, usageWidget, drawArrows, CSS
#rv-machines; web/panel.js: #rv-panel, #rv-sedit). Example machines (a laptop, an Oracle Cloud VM, an
HPC/GPU cluster) and example values. Numbered marks are explained in the key on the right.
Run: python3 ~/DirAI/docs/connections.py"""
import os
from html import escape

W, H = 1060, 840
INK, DIM, GREY = "#1d1d1f", "#77777a", "#888888"          # .dim is opacity .65 of the text colour
GREEN, RED, ORANGE, BLUE = "#2e7d32", "#c62828", "#b26b00", "#0b63ce"
TRACK = "#dcdcdc"                                          # rgba(128,128,128,.25) on white
MARK = "#b8640f"                                           # the numbered callouts (not part of the UI)
out = []


def cw(s, size=12, bold=False):
    """Rough width of s in system-ui."""
    return int(len(s) * size * (0.6 if bold else 0.54))


def text(x, y, s, size=12, color=INK, bold=False, anchor="start", italic=False):
    out.append('<text x="%d" y="%d" font-size="%s" fill="%s"%s%s text-anchor="%s">%s</text>' % (
        x, y, size, color, ' font-weight="600"' if bold else "", ' font-style="italic"' if italic else "",
        anchor, escape(s)))
    return x + cw(s, size, bold)


def spans(x, y, parts, size=12):
    """One line of (text, colour, bold) parts; returns the x after it."""
    s = "".join('<tspan fill="%s"%s>%s</tspan>' % (c, ' font-weight="600"' if b else "", escape(t)) for t, c, b in parts)
    out.append('<text x="%d" y="%d" font-size="%s" xml:space="preserve">%s</text>' % (x, y, size, s))
    return x + sum(cw(t, size, b) for t, c, b in parts)


def rect(x, y, w, h, stroke=GREY, fill="#fff", r=6, dash=None, sw=1):
    out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s" stroke="%s" stroke-width="%s"%s/>'
               % (x, y, w, h, r, fill, stroke, sw, ' stroke-dasharray="%s"' % dash if dash else ""))


def button(x, y, label, kind="blue", size=12, pad=8, r=4, h=18):
    """A button whose text baseline is y; returns the x after it plus a gap."""
    w = cw(label, size) + 2 * pad
    fill, stroke, color = {"blue": (BLUE, BLUE, "#fff"), "gray": ("none", GREY, INK), "pill": ("none", GREY, INK),
                           "pillon": (BLUE, BLUE, "#fff"), "kind": ("#fff", BLUE, BLUE), "day": ("#fff", "#999", INK),
                           "panel": ("#fafafa", "#999", INK)}[kind]
    rect(x, y - h + 5, w, h, stroke, fill, r)
    text(x + pad, y, label, size, color, kind in ("pill", "pillon"))
    return x + w + 5


def mark(x, y, n):
    out.append('<circle cx="%d" cy="%d" r="8" fill="%s"/>' % (x, y, MARK))
    text(x, y + 4, str(n), 11, "#fff", True, "middle")


def usage(x, y, five, week, stop5, stopw, reset5, resetw):
    """usageWidget as in a Machines box: title with Chart and Auto, then one line per window."""
    nx = text(x, y, "Claude usage", 12, INK, True) + 6
    nx = button(nx, y, "Chart", "pill", 11, 8, 9, 16)
    button(nx, y, "Auto", "pillon", 11, 8, 9, 16)
    for i, (label, pct, stop, reset) in enumerate((("5-hour", five, stop5, reset5), ("Weekly", week, stopw, resetw))):
        yy = y + 19 + 18 * i
        bx = text(x, yy, label, 12, INK, True) + 6
        col = RED if pct >= stop else ORANGE if pct >= 0.8 * stop else GREEN
        rect(bx, yy - 8, 40, 8, "none", TRACK, 4)
        rect(bx, yy - 8, 40 * min(pct, 100) // 100, 8, "none", col, 4)
        sx = bx + 40 * stop // 100
        out.append('<rect x="%d" y="%d" width="4" height="16" fill="%s"/>' % (sx - 2, yy - 12, INK))   # the slider thumb
        spans(bx + 46, yy, [("%d%%" % pct, INK, False), (" · %s · pause %d%%" % (reset, stop), DIM, False)])
    return y + 19 + 18 + 12


def tnode(x, y, w, h, lines, state="alive"):
    """treeNode: green border (alive), dashed grey (down); the show checkbox on the right."""
    rect(x, y, w, h, GREEN if state == "alive" else GREY, "#fff", 6, None if state == "alive" else "4 3")
    rect(x + w - 19, y + 6, 12, 12, "#767676", "#fff" if state != "alive" else BLUE, 2)
    if state == "alive":
        out.append('<path d="M%d %d l3 3 l5 -6" fill="none" stroke="#fff" stroke-width="2"/>' % (x + w - 16, y + 12))
    for i, ln in enumerate(lines):
        if callable(ln):
            ln(x + 6, y + 17 + 16 * i)
        else:
            spans(x + 6, y + 17 + 16 * i, ln)


def machbox(x, y, w, h, name, sub, remote=True):
    rect(x, y, w, h, GREY, "#fff", 8)
    spans(x + 8, y + 19, [("▾ ", DIM, False), (name, INK, True), ("  " + sub, DIM, False)], 13)
    if remote:
        text(x + w - 12, y + 18, "×", 16, GREY, False, "middle")


def arrow(x1, y1, x2, y2):
    """drawArrows: side by side, facing edges at top + 24, a green cubic (link up)."""
    mx = (x1 + x2) // 2
    out.append('<path d="M%d,%d C%d,%d %d,%d %d,%d" fill="none" stroke="%s" stroke-width="2" marker-end="url(#ah)"/>'
               % (x1, y1, mx, y1, mx, y2, x2, y2, GREEN))


# ---------------------------------------------------------------- title
text(20, 26, "Every machine in one list: ssh links, Claude usage limits and schedules", 17, INK, True)
text(20, 44, "The agent list's Machines section and one agent's panel (example values)", 12, DIM)

# ---------------------------------------------------------------- Machines section
spans(20, 72, [("▾ ", DIM, False), ("Machines — 4 servers on 3 machines · ", INK, True), ("1 needs you", INK, True)], 13)

X1, X2, X3, Y = 20, 406, 752, 84
arrow(350, Y + 24, X2, Y + 24)
arrow(X2 + 290, Y + 24, X3, Y + 24)
mark(378, Y + 12, 1)

# this server: a laptop
machbox(X1, Y, 330, 232, "MacBook", "this server", remote=False)
uy = usage(X1 + 8, Y + 42, 34, 48, 80, 57, "15:10", "Sat 9 AM")
mark(X1 + 316, Y + 38, 2)
mark(X1 + 316, Y + 58, 3)
mark(X1 + 226, Y + 38, 4)
tnode(X1 + 8, uy, 314, 40, [[("~/work", INK, True)],
                            lambda x, y: button(spans(x, y, [("alive · this list", GREEN, False)]) + 6, y, "Restart", "gray")])
y = uy + 58
text(X1 + 8, y, "DirAI main @ 52a5d4e", 12, DIM)
text(X1 + 8, y + 16, "up to date with origin/main · fetched 4 min ago", 12, DIM)
text(X1 + 8, y + 38, "Connect from ~/.ssh/config:", 12, DIM)
rect(X1 + 8, y + 45, 110, 18, "#767676", "#fff", 3)
text(X1 + 14, y + 58, "hpc-gpu", 12)
text(X1 + 110, y + 58, "▾", 10, INK, False, "end")
button(X1 + 124, y + 58, "Connect", "blue")

# an Oracle Cloud VM, linked by the laptop
machbox(X2, Y, 290, 232, "oracle-vm", "ssh on instance-oci1")
uy = usage(X2 + 8, Y + 42, 12, 30, 100, 57, "18:40", "Sat 9 AM")
tnode(X2 + 8, uy, 274, 56, [[("~/webapp", INK, True)],
                            [("alive", GREEN, False), (" · instance-oci1 · 8765", DIM, False)],
                            lambda x, y: button(button(button(text(x, y, "4 agents") + 6, y, "Open"), y, "Restart", "gray"),
                                                y, "Stop…", "gray")])
y = uy + 76
text(X2 + 8, y, "New tree…", 12, DIM)
text(X2 + 8, y + 22, "Connect from ~/.ssh/config:", 12, DIM)
text(X2 + 8, y + 38, "its one host is connected", 12, DIM)

# an HPC/GPU cluster, linked by the Oracle VM (a chain)
machbox(X3, Y, 290, 332,"hpc-gpu", "ssh on login1")
uy = usage(X3 + 8, Y + 42, 71, 52, 80, 57, "16:25", "Sat 9 AM")
tnode(X3 + 8, uy, 274, 72, [[("~/proj/sim", INK, True)],
                            [("alive", GREEN, False), (" · gpu-a07 · 8765", DIM, False)],
                            [("12 agents · ", INK, False), ("1 needs you", RED, True)],
                            lambda x, y: button(button(button(x, y, "Open"), y, "Restart", "gray"), y, "Stop…", "gray")])
mark(X3 + 150, uy + 29, 5)
mark(X3 + 166, uy + 45, 6)
tnode(X3 + 8, uy + 80, 274, 88, [[("/scratch/…/train", INK, True)],
                                 [("down", GREY, False), (" · – · 8766", DIM, False)],
                                 lambda x, y: button(text(x, y, "0 agents") + 6, y, "Start"),
                                 [("last server gpu-a03: job 812345", DIM, False)],
                                 [("ended (TIMEOUT)", DIM, False)]], "down")
y = uy + 188
text(X3 + 8, y, "New tree…", 12, DIM)
text(X3 + 8, y + 22, "Connect from ~/.ssh/config:", 12, DIM)
text(X3 + 8, y + 38, "no Host entries there", 12, DIM)

# ---------------------------------------------------------------- an agent's panel (panel.js)
PX, PY, PW = 20, 432, 500
rect(PX, PY, PW, 346, "#bbbbbb", "#fff", 10)
text(PX + 12, PY + 24, "hpc-gpu:~/proj/sim", 14, INK, True)
rect(PX + PW - 82, PY + 11, 70, 18, "none", ORANGE, 9)
text(PX + PW - 47, PY + 24, "working", 12, "#fff", True, "middle")
out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ddd"/>' % (PX, PY + 38, PX + PW, PY + 38))
rect(PX + 12, PY + 48, PW - 24, 38, "none", "#eef4ff", 8)
text(PX + 22, PY + 62, "you (scheduled, every day) · 08:00", 11, "#777")
text(PX + 22, PY + 78, "Rerun the fit with last night's data and update the plots", 13)
rect(PX + 12, PY + 92, PW - 24, 38, "none", "#f3f3f3", 8)
text(PX + 22, PY + 106, "claude · 08:41 · $0.38", 11, "#777")
text(PX + 22, PY + 122, "Submitted 3 GPU jobs; I'll update the plots when they finish.", 13)
mark(PX + 166, PY + 102, 8)
out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ddd"/>' % (PX, PY + 140, PX + PW, PY + 140))
bx = button(PX + 12, PY + 164, "📎", "panel", 13, 10, 6, 24)
bx = button(bx + 1, PY + 164, "Schedule…", "panel", 13, 10, 6, 24)
mark(bx - 4, PY + 146, 7)
bx = button(bx + 1, PY + 164, "New chat", "panel", 13, 10, 6, 24)
button(bx + 1, PY + 164, "TaskDone", "panel", 13, 10, 6, 24)
# #rv-sedit
SY = PY + 178
rect(PX + 12, SY, PW - 24, 124, "none", "#f3f3f3", 6)
text(PX + 20, SY + 20, "Send", 12.5)
kx = PX + 78
for k in ("Once", "Daily", "Weekly", "Every hour"):
    kx = button(kx, SY + 20, k, "kind" if k != "Daily" else "pillon", 12.5, 10, 12, 20)
text(PX + 20, SY + 46, "at", 12.5)
rect(PX + 78, SY + 32, 64, 20, "#999", "#fff", 4)
text(PX + 84, SY + 46, "08:00", 13)
rect(PX + 20, SY + 58, PW - 40, 24, "#999", "#fff", 2)
text(PX + 26, SY + 74, "Rerun the fit with last night's data and update the plots", 13)
text(PX + 20, SY + 100, "Each run", 12.5)
out.append('<circle cx="%d" cy="%d" r="5" fill="#fff" stroke="#767676"/>' % (PX + 84, SY + 96))
text(PX + 94, SY + 100, "fresh chat (re-reads index.html)", 12.5)
out.append('<circle cx="%d" cy="%d" r="5" fill="#fff" stroke="%s" stroke-width="3"/>' % (PX + 346, SY + 96, BLUE))
text(PX + 356, SY + 100, "continue this chat", 12.5)
bx = button(PX + 12, SY + 148, "Save schedule", "blue", 13, 10, 6, 24)
button(bx + 1, SY + 148, "Cancel", "panel", 13, 10, 6, 24)

# ---------------------------------------------------------------- the key
KX, KY = 548, 446
text(KX, KY, "What the numbers point at", 14, INK, True)
key = [   # one short line each; the details are in docs/index.html, "How the machines connect"
    (1, ["ssh link to the next machine. Chains work."]),
    (2, ["That machine's Claude usage."]),
    (3, ["Pause level: drag it. No new runs above it."]),
    (4, ["Auto: weekly level grows 1/7 a day."]),
    (5, ["Compute node serving the tree."]),
    (6, ["An agent waits for you."]),
    (7, ["Schedule: runs with the laptop closed."]),
    (8, ["What the reply cost."]),
]
y = KY + 24
for n, lines in key:
    mark(KX + 8, y - 4, n)
    for i, ln in enumerate(lines):
        text(KX + 24, y + 15 * i, ln, 12)
    y += 15 * len(lines) + 8
text(KX, y + 6, "Agents run on their own machines; the laptop only shows them.", 12, DIM, italic=True)

out.insert(0, '<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
              '<path d="M0,0 L8,4 L0,8 z" fill="%s"/></marker></defs>' % GREEN)
svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
       'font-family="system-ui, -apple-system, Segoe UI, sans-serif">\n<rect width="100%%" height="100%%" fill="#fff"/>\n%s\n</svg>\n'
       % (W, H, W, H, "\n".join(out)))
dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connections.svg")
with open(dest, "w") as f:
    f.write(svg)
print("wrote", dest)
