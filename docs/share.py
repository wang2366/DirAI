"""Draw share.svg for README "Share agents with other people" (proposal 72: lib/shares.py, web/share.js):
your agent's folder -> Publish -> a private repo in your own GitHub org (readers get the Read role)
-> a friend's (Mary's) agent list, read-only, where they use it as a colleague or copy it to their tree.
Run: python3 ~/DirAI/docs/share.py"""
import os
from html import escape

W, H = 900, 330
o = []


def t(x, y, s, size=13, fill="#222", anchor="middle", bold=False, mono=False):
    o.append('<text x="%d" y="%d" font-size="%d" fill="%s" text-anchor="%s"%s%s>%s</text>' % (
        x, y, size, fill, anchor, ' font-weight="bold"' if bold else "",
        ' font-family="monospace"' if mono else "", escape(s)))


def rect(x, y, w, h, fill, stroke, r=10, sw=1.5, dash=False):
    o.append('<rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s" stroke="%s" stroke-width="%s"%s/>'
             % (x, y, w, h, r, fill, stroke, sw, ' stroke-dasharray="5 4"' if dash else ""))


def arrow(x1, x2, y, label, sub):
    o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#555" stroke-width="2"/>' % (x1, y, x2 - 8, y))
    o.append('<polygon points="%d,%d %d,%d %d,%d" fill="#555"/>' % (x2, y, x2 - 10, y - 6, x2 - 10, y + 6))
    t((x1 + x2) // 2, y - 10, label, 13, "#222", bold=True)
    t((x1 + x2) // 2, y + 20, sub, 11, "#777")


def pill(x, y, label, fill, ink="#fff"):
    w = len(label) * 7 + 18
    rect(x, y, w, 22, fill, fill, 11, 1)
    t(x + w // 2, y + 15, label, 12, ink, bold=True)


o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica, Arial, sans-serif">' % (W, H, W, H))
o.append('<rect width="%d" height="%d" fill="#fff"/>' % (W, H))
t(W // 2, 30, "Share an agent: you publish, they read", 19, "#222", bold=True)

# you
rect(20, 60, 230, 250, "#f4f8ff", "#3d6fae")
t(135, 84, "You", 15, "#3d6fae", bold=True)
rect(40, 98, 190, 92, "#fff", "#999", 6, 1)
t(135, 118, "~/proj/fit/  (an agent)", 12, "#222", mono=True)
t(135, 140, "page · scripts · results", 12, "#555")
pill(68, 156, "Share", "#3d6fae")
pill(142, 156, "Chat", "#ddd", "#555")
t(135, 216, "stays with you:", 12, "#777")
t(135, 234, "chat, Claude session, grants", 12, "#777")
t(135, 268, "one click, or after each run", 12, "#3d6fae")

# GitHub
arrow(252, 340, 150, "Publish", "a snapshot")
rect(340, 60, 220, 250, "#f6f6f6", "#444")
t(450, 84, "GitHub", 15, "#222", bold=True)
rect(358, 98, 184, 92, "#fff", "#999", 6, 1)
t(450, 118, "<login>-dirai /", 12, "#222", mono=True)
t(450, 136, "<login>_agent_repo", 12, "#222", mono=True)
t(450, 158, "private · agents/fit/", 12, "#555")
t(450, 178, "your free org", 11, "#777")
t(450, 216, "readers: Read role", 12, "#222", bold=True)
t(450, 234, "so they can't push", 12, "#777")
t(450, 268, "one repo per audience", 12, "#444")

# labmate
arrow(562, 650, 150, "Connect", "from GitHub")
rect(650, 60, 230, 250, "#f2faf4", "#2f7d4a")
t(765, 84, "Your friend Mary", 15, "#2f7d4a", bold=True)
rect(668, 98, 194, 92, "#fff", "#2f7d4a", 6, 1, dash=True)
t(765, 118, "fit  (in their agent list)", 12, "#222")
t(765, 140, "From you · read-only", 12, "#2f7d4a", bold=True)
t(765, 160, "new versions marked", 12, "#555")
t(765, 178, "every 10 min", 11, "#777")
t(765, 222, "Use as colleague", 13, "#222", bold=True)
t(765, 240, "their agents read it", 12, "#777")
t(765, 268, "Copy to my tree", 13, "#222", bold=True)
t(765, 286, "run it on their own Claude", 12, "#777")
o.append("</svg>")

dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "share.svg")
with open(dest, "w", encoding="utf-8") as f:
    f.write("\n".join(o) + "\n")
print("wrote", dest)
