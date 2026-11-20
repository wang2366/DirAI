"""Draw night.svg: "24/7 agents" as one evening-to-morning timeline of a real kind of task.
Run: python3 ~/DirAI/docs/night.py"""
import os

W, H = 900, 250
o = []


def t(x, y, s, size=13, fill="#222", anchor="middle", bold=False):
    o.append('<text x="%d" y="%d" font-size="%d" fill="%s" text-anchor="%s"%s>%s</text>' % (
        x, y, size, fill, anchor, ' font-weight="bold"' if bold else "", s.replace("&", "&amp;")))


o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica, Arial, sans-serif">' % (W, H, W, H))
o.append('<rect width="%d" height="%d" fill="#fff"/>' % (W, H))
t(W // 2, 30, "Works while you sleep: one night of an agent", 20, "#222", bold=True)
# night shading between 22:00 and 07:00 on an 18:00 -> 09:00 axis (15 h over 60..840)
X0, X1 = 60, 840
x = lambda h: X0 + (X1 - X0) * ((h - 18) % 24) / 15.0
o.append('<rect x="%d" y="60" width="%d" height="110" rx="8" fill="#eef0f7"/>' % (x(22), x(7) - x(22)))
t(x(23.5), 76, "you are asleep", 12, "#6b7394")
o.append('<line x1="%d" y1="120" x2="%d" y2="120" stroke="#888" stroke-width="2"/>' % (X0, X1))
for h in [18, 20, 22, 0, 2, 4, 6, 8]:
    o.append('<line x1="%d" y1="115" x2="%d" y2="125" stroke="#888"/>' % (x(h), x(h)))
    t(x(h), 142, "%02d:00" % h, 11, "#777")
events = [(18.5, "#3d6fae", "You: \"rerun the fit", "with 10x the data\""),
          (19.0, "#2f7d4a", "Agent submits", "200 cluster jobs"),
          (3.5, "#555", "Jobs finish; DirAI", "wakes the agent"),
          (4.0, "#2f7d4a", "Agent updates plots", "and its report"),
          (8.0, "#3d6fae", "You: read the result,", "changes in yellow")]
for i, (h, col, a, b) in enumerate(events):
    up = i % 2 == 0
    o.append('<circle cx="%d" cy="120" r="7" fill="%s"/>' % (x(h), col))
    y = 98 if up else 170
    o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s"/>' % (x(h), 113 if up else 127, x(h), y + (4 if up else -12), col))
    t(x(h), (y - 16) if up else (y + 4), a, 12, col, bold=True)
    t(x(h), (y - 2) if up else (y + 18), b, 12, col)
t(W // 2, 232, "Tokens are used only while the agent works: waiting for jobs is free (checked every 10 min).", 12, "#555")
o.append("</svg>")

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "night.svg")
open(path, "w").write("\n".join(o) + "\n")
print("wrote", path)
