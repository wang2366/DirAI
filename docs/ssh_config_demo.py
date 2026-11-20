"""Make ssh_config_demo.gif: make a key, write a new ~/.ssh/config with one Host in vim (starting from none), log in once by hand with ssh-copy-id
(answer yes to the new host key, type the password), check it with BatchMode ssh, and see it appear
in the agent list's "Connect from ~/.ssh/config" dropdown; then Connect it, and start a tree there with
New tree… (path, node, Init and start; agent_list.js newTree, treeNode). The browser side follows
web/agent_list.js (connectPicker, machineBox, dirai(), drawArrows): the picker lists the Host entries not
connected yet, re-read at every redraw (lib/remotes.py report() calls ssh_hosts() each time, every 10 s).
Example machines and names. Run: python3 ~/DirAI/docs/ssh_config_demo.py"""
import os

import matplotlib
import numpy as np
from matplotlib.ft2font import FT2Font, LOAD_FORCE_AUTOHINT
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1000, 560
TW = 500                      # terminal width; the browser takes the rest

# This Pillow has no FreeType (_imagingft), so text is drawn with matplotlib's FT2Font and its bundled DejaVu fonts
TTF = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
MONO = (os.path.join(TTF, "DejaVuSansMono.ttf"), 14)
SANS = (os.path.join(TTF, "DejaVuSans.ttf"), 13)
SANSB = (os.path.join(TTF, "DejaVuSans-Bold.ttf"), 13)
SMALL = (os.path.join(TTF, "DejaVuSans.ttf"), 12)
CAP = (os.path.join(TTF, "DejaVuSans-Bold.ttf"), 16)
_fonts, _cache = {}, {}


def render(s, font):
    """(alpha mask, advance width, height above the baseline of the mask's top) of s in font."""
    k = (s, font)
    if k not in _cache:
        f = _fonts.get(font)
        if f is None:
            f = _fonts[font] = FT2Font(font[0])
        f.set_size(font[1], 72)
        f.set_text(s, 0.0, flags=LOAD_FORCE_AUTOHINT)
        f.draw_glyphs_to_bitmap(antialiased=True)
        a = np.array(f.get_image(), dtype=np.uint8, copy=True)    # FT2Font reuses its buffer
        _cache[k] = (Image.fromarray(a) if a.size else None, f.get_width_height()[0] / 64.0, a.shape[0] - f.get_descent() / 64.0)
    return _cache[k]


def _sc(v, s):
    """v (a number, a point, or a list of them) times s."""
    if isinstance(v, (list, tuple)):
        return type(v)(_sc(e, s) for e in v)
    return v * s


class Draw:
    """ImageDraw with text() and textlength() done by render(); anchors l/m/r x a/m. The drawing code
    works in full-size coordinates; with s < 1 every shape, line width and font size is scaled here, so
    the GIF is drawn natively at the small size (crisp hinted text), not shrunk afterwards (blurry)."""

    def __init__(self, im, s=1.0):
        self.im, self.d, self.s = im, ImageDraw.Draw(im), s

    def __getattr__(self, name):
        f = getattr(self.d, name)
        s = self.s

        def call(xy, *a, **k):
            if name == "rounded_rectangle" and a:
                a = (a[0] * s,) + a[1:]
            for key in ("radius", "width"):
                if key in k:
                    k[key] = max(1, round(k[key] * s))
            return f(_sc(xy, s), *a, **k)
        return call

    def textlength(self, s, font):
        return render(s, (font[0], font[1] * self.s))[1] / self.s if s else 0

    def text(self, xy, s, font, fill, anchor="la"):
        if not s:
            return
        font = (font[0], font[1] * self.s)
        mask, w, above = render(s, font)
        if mask is None:
            return
        x, y = xy[0] * self.s, xy[1] * self.s
        x -= {"l": 0, "m": w / 2, "r": w}[anchor[0]]
        base = y + 0.93 * font[1] if anchor[1] == "a" else y + 0.36 * font[1]
        self.im.paste(fill, (int(round(x)), int(round(base - above))), mask)

INK, DIM, GREY, GREEN, RED, BLUE = "#1d1d1f", "#77777a", "#888888", "#2e7d32", "#c62828", "#0b63ce"
T_BG, T_FG, T_DIM, T_BLUE, T_GREEN, T_YEL = "#1e1e1e", "#d4d4d4", "#808080", "#569cd6", "#6a9955", "#dcdcaa"
LH = 19

NEW = ["Host hpc-gpu", "    HostName login.hpc.example.edu", "    User you", "    IdentityFile ~/.ssh/id_ed25519"]


def color_conf(line):
    """vim's sshconfig colours: keywords blue, the rest plain."""
    s = line.lstrip()
    if not s:
        return [(line, T_FG)]
    kw, _, rest = s.partition(" ")
    return [(line[:len(line) - len(s)], T_FG), (kw, T_BLUE if kw == "Host" else T_YEL), (" " + rest if rest else "", T_FG)]


def draw_terminal(d, st):
    d.rectangle([0, 0, TW, H], fill=T_BG)
    d.rectangle([0, 0, TW, 28], fill="#323233")
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        d.ellipse([12 + 18 * i, 9, 24 + 18 * i, 21], fill=c)
    d.text((TW // 2, 14), "Terminal: laptop", font=SMALL, fill="#cccccc", anchor="mm")
    y0 = 40
    if st["mode"] == "shell":
        for i, parts in enumerate(st["shell"]):
            x = 10
            for txt, col in parts:
                d.text((x, y0 + LH * i), txt, font=MONO, fill=col)
                x += d.textlength(txt, font=MONO)
            if i == len(st["shell"]) - 1 and st.get("cursor", True):
                d.rectangle([x + 1, y0 + LH * i + 1, x + 9, y0 + LH * i + 17], fill=T_FG)
        return
    # vim
    lines = st["buf"]
    rows = (H - 40 - 2 * LH) // LH
    for i in range(rows):
        y = y0 + LH * i
        if i < len(lines):
            x = 10
            for txt, col in color_conf(lines[i]):
                d.text((x, y), txt, font=MONO, fill=col)
                x += d.textlength(txt, font=MONO)
            if st.get("cur") == i:
                d.rectangle([x + 1, y + 1, x + (2 if st["insert"] else 9), y + 17], fill=T_FG)
        else:
            d.text((10, y), "~", font=MONO, fill=T_BLUE)
    ys = H - 2 * LH - 6
    d.text((10, ys + LH), st["status"], font=MONO, fill=T_FG if not st["insert"] else "#ffffff")


def btn(d, x, y, label, kind="blue", f=SMALL):
    w = d.textlength(label, font=f) + 16
    fill, out, col = {"blue": (BLUE, BLUE, "#fff"), "gray": ("#fff", GREY, INK)}[kind]
    d.rounded_rectangle([x, y, x + w, y + 19], 4, fill=fill, outline=out)
    d.text((x + 8, y + 10), label, font=f, fill=col, anchor="lm")
    return x + w + 6


def arrow_curve(d, p1, p2, col, dash=False):
    """drawArrows' wrapped case: bottom of the parent (left + 30) to the top of the child (left + 30)."""
    (x1, y1), (x2, y2) = p1, p2
    pts = [(x1 + (x2 - x1) * t / 20.0, y1 + (y2 - y1) * t / 20.0) for t in range(21)]
    for i in range(20):
        if dash and i % 2:
            continue
        d.line([pts[i], pts[i + 1]], fill=col, width=2)
    d.polygon([(x2, y2), (x2 - 5, y2 - 8), (x2 + 5, y2 - 8)], fill=col)


def draw_browser(d, st):
    X = TW
    d.rectangle([X, 0, W, H], fill="#ffffff")
    d.rectangle([X, 0, W, 28], fill="#e8e8ea")
    d.rounded_rectangle([X + 14, 5, W - 14, 23], 9, fill="#ffffff")
    d.text((X + 26, 14), "127.0.0.1:8765/www/index.html", font=SMALL, fill=DIM, anchor="lm")
    bx = X + 18
    d.text((bx, 44), "Agents", font=CAP, fill=INK)
    d.text((bx, 72), "▾ Machines", font=SANSB, fill=INK)
    # this server's box
    m = [bx, 92, bx + 300, 92 + 178]
    d.rounded_rectangle(m, 8, outline=GREY, fill="#fff")
    d.text((bx + 8, 100), "▾ ", font=SANS, fill=DIM)
    d.text((bx + 22, 100), "MacBook", font=SANSB, fill=INK)
    d.text((bx + 28 + d.textlength("MacBook", SANSB), 100), "this server", font=SANS, fill=DIM)
    d.text((bx + 8, 124), "Claude usage", font=SANSB, fill=INK)
    for i, (lab, pct, stop) in enumerate((("5-hour", 34, 80), ("Weekly", 48, 57))):
        y = 144 + 18 * i
        d.text((bx + 8, y), lab, font=SANSB, fill=INK)
        b0 = bx + 70
        d.rounded_rectangle([b0, y + 4, b0 + 40, y + 12], 4, fill="#dcdcdc")
        d.rounded_rectangle([b0, y + 4, b0 + 40 * pct // 100, y + 12], 4, fill=GREEN)
        sx = b0 + 40 * stop // 100
        d.rectangle([sx - 2, y, sx + 1, y + 16], fill=INK)
        d.text((b0 + 48, y), "%d%% · pause %d%%" % (pct, stop), font=SMALL, fill=DIM)
    d.rounded_rectangle([bx + 8, 184, bx + 292, 218], 6, outline=GREEN, fill="#fff")
    d.text((bx + 14, 188), "~/work", font=SANSB, fill=INK)
    d.text((bx + 14, 203), "alive · this list", font=SMALL, fill=GREEN)
    btn(d, bx + 22 + d.textlength("alive · this list", SMALL), 199, "Restart", "gray")
    d.text((bx + 8, 226), "Connect from ~/.ssh/config:", font=SMALL, fill=DIM)
    free = [h for h in st["hosts"] if h not in st["connected"]]
    sel = st["sel"] if st["sel"] in free else (free[0] if free else None)
    sy = 244
    if sel:
        d.rectangle([bx + 8, sy, bx + 128, sy + 19], outline="#767676", fill="#fff")
        d.text((bx + 14, sy + 10), sel, font=SMALL, fill=INK, anchor="lm")
        d.text((bx + 120, sy + 10), "▾", font=SMALL, fill=INK, anchor="rm")
        btn(d, bx + 134, sy, "Connect")
    else:
        # connectPicker's words when nothing is free
        d.text((bx + 8, sy + 4), "no Host entries there" if not st["hosts"] else "its one host is connected", font=SMALL, fill=DIM)
    # a connected host: its box, below (the wrapped layout), with the link arrow
    if st["connected"]:
        state = st["link"]
        nt = st.get("nt")
        grow = {"open": 80, "starting": 48, "alive": 32}.get(nt, 0)
        c = [bx, 300, bx + 300, 300 + (128 + grow if state == "up" else 58)]
        col = {"connecting": RED, "updating": GREY, "up": GREEN}[state]
        arrow_curve(d, (bx + 30, 270), (bx + 30, 299), col, dash=state != "up")
        d.rounded_rectangle(c, 8, outline=RED if state == "connecting" else GREY, fill="#fff")
        d.text((bx + 8, 308), "▾ ", font=SANS, fill=DIM)
        d.text((bx + 22, 308), "hpc-gpu", font=SANSB, fill=INK)
        if state == "up":
            d.text((bx + 28 + d.textlength("hpc-gpu", SANSB), 308), "ssh on login1", font=SANS, fill=DIM)
        d.text((bx + 288, 314), "×", font=CAP, fill=GREY, anchor="mm")
        if state == "connecting":
            d.text((bx + 8, 330), "connecting…", font=SMALL, fill=RED)
        elif state == "updating":
            d.text((bx + 8, 330), "copying DirAI there…", font=SMALL, fill=DIM)
        else:
            y = 330
            if nt in ("starting", "alive"):
                # treeNode: green border when alive; "starting…" until its server answers
                d.rounded_rectangle([bx + 8, y, bx + 292, y + 58], 6, outline=GREEN if nt == "alive" else GREY, fill="#fff")
                d.text((bx + 14, y + 4), st["path"], font=SANSB, fill=INK)
                if nt == "alive":
                    d.text((bx + 14, y + 20), "alive", font=SMALL, fill=GREEN)
                    d.text((bx + 14 + d.textlength("alive", SMALL), y + 20), " · login1 · 8765", font=SMALL, fill=DIM)
                    x = btn(d, bx + 14 + d.textlength("0 agents ", SMALL), y + 35, "Open")
                    btn(d, btn(d, x, y + 35, "Restart", "gray"), y + 35, "Stop…", "gray")
                else:
                    d.text((bx + 14, y + 20), "– · –", font=SMALL, fill=DIM)
                    d.text((bx + 14 + d.textlength("0 agents ", SMALL), y + 38), "starting…", font=SMALL, fill=DIM)
                d.text((bx + 14, y + 38), "0 agents", font=SMALL, fill=INK)
                y += 66
            else:
                d.text((bx + 8, y), "no DirAI trees there yet", font=SMALL, fill=DIM)
                y += 18
            if nt == "open":
                # newTree(): a path (made if missing), a node, Init and start
                d.text((bx + 8, y), "▾ New tree…", font=SMALL, fill=DIM)
                y += 20
                for val, ph in ((st.get("path", ""), "~/project (made if missing), or pick a known one"),
                                (st.get("node", ""), "node: empty, a node name or --job")):
                    d.rectangle([bx + 8, y, bx + 292, y + 20], outline="#767676", fill="#fff")
                    d.text((bx + 13, y + 10), val or ph, font=SMALL, fill=INK if val else "#aaaaaa", anchor="lm")
                    y += 26
                btn(d, bx + 8, y, "Init and start")
                y += 30
            else:
                d.text((bx + 8, y), "New tree…", font=SMALL, fill=DIM)
                y += 22
            d.text((bx + 8, y), "Connect from ~/.ssh/config:", font=SMALL, fill=DIM)
            if nt == "alive":
                d.text((bx + 8, y + 16), "no Host entries there", font=SMALL, fill=DIM)
            else:
                d.text((bx + 8, y + 16), "once a DirAI server runs there", font=SMALL, fill=DIM)
                d.text((bx + 8, y + 32), "(Start or New tree)", font=SMALL, fill=DIM)
    # the open dropdown
    if st.get("open") and free:
        oy = sy + 20
        d.rectangle([bx + 8, oy, bx + 128, oy + 20 * len(free)], outline="#767676", fill="#fff")
        for i, h in enumerate(free):
            y = oy + 20 * i
            if h == st.get("hover"):
                d.rectangle([bx + 9, y + 1, bx + 127, y + 19], fill=BLUE)
            d.text((bx + 14, y + 10), h, font=SMALL, fill="#fff" if h == st.get("hover") else INK, anchor="lm")
            if h == "hpc-gpu":
                d.text((bx + 136, y + 10), "← new", font=SANSB, fill="#b8640f", anchor="lm")
    if st.get("hint"):          # what the dropdown holds now, so the existing host isn't read as the new one
        for i, s in enumerate(st["hint"]):
            d.text((bx + 8, 294 + 16 * i), s, font=SANSB if i == 0 else SMALL, fill="#b8640f")
    if st.get("note"):
        d.text((bx + 110, 72), "(" + st["note"] + ")", font=SMALL, fill=DIM)
    if st.get("mouse"):
        mx, my = st["mouse"]
        pts = [(mx, my), (mx, my + 17), (mx + 4, my + 13), (mx + 8, my + 20), (mx + 11, my + 19), (mx + 7, my + 12), (mx + 12, my + 12)]
        d.polygon(pts, fill="#000", outline="#fff")


CAPH = 56                     # the caption bar under each GIF: up to 2 lines (3 on the narrow browser GIFs)
BCAPH = 66                    # the browser GIFs' caption bar (3 lines of 13 px)
BW, BH = 340, H + CAPH - BCAPH  # the browser GIFs: just the machine column (300 px) and its margins, so two
                              # fit side by side in a README (about 830 px wide on GitHub); BH makes all
                              # three GIFs the same height (616 px) so they line up in one row
SCALE = 0.66                  # every frame is drawn natively at this scale (Draw scales coordinates and font
                              # sizes; shrinking a full-size frame blurred the text), so the 3 GIFs together
                              # (500 + 340 + 340 = 1180 px drawn) are 779 px wide and fit one row of
                              # GitHub's README column (about 830 px on a wide window)


def wrap(d, s, font, width):
    lines = [""]
    for w in s.split(" "):
        t = (lines[-1] + " " + w).strip()
        if d.textlength(t, font=font) <= width or not lines[-1]:
            lines[-1] = t
        else:
            lines.append(w)
    return lines


def frame(st):
    """One frame of the current GIF: the terminal half ("term") or the browser half ("connect", "newtree"),
    with the step caption under it."""
    S = SCALE
    im = Image.new("RGB", (round(W * S), round(H * S)), "#ffffff")
    d = Draw(im, S)
    if PART == "term":
        draw_terminal(d, st)
        box = (0, 0, TW, H)
    else:
        draw_browser(d, st)
        box = (TW, 0, TW + BW, BH)
    w, h = box[2] - box[0], box[3] - box[1]
    f = CAP if PART == "term" else SANSB
    lines = wrap(d, st["cap"], f, w - 28)
    ch = CAPH if PART == "term" else BCAPH
    out = Image.new("RGB", (round(w * S), round((h + ch) * S)), "#ffffff")
    out.paste(im.crop(tuple(round(v * S) for v in box)), (0, 0))
    d = Draw(out, S)
    d.rectangle([0, h, w, h + ch], fill="#f5f5f7")
    d.line([0, h, w, h], fill="#cccccc")
    step = 21 if PART == "term" else 18
    for i, s in enumerate(lines):
        d.text((14, h + ch / 2 + (i - (len(lines) - 1) / 2.0) * step), s, font=f, fill=INK, anchor="lm")
    return out


PARTS = [("term", "ssh_config_demo.gif"), ("connect", "connect_demo.gif"), ("newtree", "new_tree_demo.gif")]
frames = {p: [] for p, _ in PARTS}
PART = "term"


def add(st, ms):
    frames[PART].append((frame(st), ms))


PROMPT = ("$ ", T_GREEN)


def typed(st, hist, prefix, text, step=2, ms=55, col=T_FG):
    """Frames of text typed after prefix (a list of (text, colour)) below the lines in hist."""
    for i in list(range(0, len(text), step)) + [len(text)]:
        add(dict(st, shell=hist + [prefix + [(text[:i], col)]]), ms)
    return hist + [prefix + [(text, col)]]


def out(lines, col=T_DIM):
    return [[(s, col)] for s in lines]


base = {"mode": "shell", "shell": [[PROMPT]], "hosts": [], "connected": [], "sel": None,
        "hint": ["No ~/.ssh/config yet,", "so there is nothing to Connect to."],
        "link": None, "cap": "1. Once per laptop: make an ssh key (skip if ~/.ssh/id_ed25519 exists)", "insert": False}
add(base, 900)
# step 1: the key. Empty passphrase, or one that ssh-agent holds: DirAI's ssh can't type it.
hist = typed(base, [], [PROMPT], "ssh-keygen -t ed25519", step=1, ms=60)
add(dict(base, shell=hist + out(["Generating public/private ed25519 key pair."])), 400)
hist = hist + out(["Generating public/private ed25519 key pair.", "Enter file in which to save the key",
                   "  (/home/you/.ssh/id_ed25519):"])
add(dict(base, shell=hist), 700)
kg = dict(base, cap="1. Empty passphrase, or one kept in ssh-agent: DirAI's ssh can't type it")
hist = hist + out(["Enter passphrase (empty for no passphrase):", "Enter same passphrase again:"])
add(dict(kg, shell=hist), 1300)
hist = hist + out(["Your public key has been saved in", "  /home/you/.ssh/id_ed25519.pub"])
add(dict(kg, shell=hist + [[PROMPT]]), 1600)
# step 2: open the config
base = dict(base, cap="2. Open ~/.ssh/config in an editor")
cmd = "vim ~/.ssh/config"
for i in range(1, len(cmd) + 1):
    add(dict(base, shell=[[PROMPT, (cmd[:i], T_FG)]]), 70)
add(dict(base, shell=[[PROMPT, (cmd, T_FG)]]), 400)
# no ~/.ssh/config yet: vim opens a new, empty file, and the dropdown has nothing to offer
vim = dict(base, mode="vim", buf=[""], cur=0, status='"~/.ssh/config" [New]')
add(dict(vim, cap="2. No ~/.ssh/config yet: an empty file, and nothing to Connect to"), 2400)
add(dict(vim, cap="3. Add a Host entry for the new machine (i: insert)"), 700)
# insert the new block, a few characters per frame
ins = dict(vim, insert=True, status="-- INSERT --", cap="3. Add a Host entry for the new machine")
buf = []
for line in NEW:
    buf.append("")
    for i in range(0, len(line) + 1, 3):
        buf[-1] = line[:i]
        add(dict(ins, buf=list(buf), cur=len(buf) - 1), 45)
    buf[-1] = line
    add(dict(ins, buf=list(buf), cur=len(buf) - 1), 220)
# save and quit
done = dict(vim, buf=list(buf), cur=len(buf) - 1, cap="4. Save and quit: Esc, :wq")
add(dict(done, status=""), 400)
for i in range(1, 4):
    add(dict(done, status=":wq"[:i]), 160)
add(dict(done, status=":wq"), 400)
add(dict(done, status='"~/.ssh/config" [New] 4L, 96B written'), 600)
# step 5: the one manual login. ssh-copy-id puts the key there; ssh asks to trust the new host key ("yes")
# and for the password, both for the last time. DirAI's own ssh (BatchMode=yes) could answer neither.
sh = dict(base, hint=None, cap="5. Once per machine: copy your key there, by hand")
hist = typed(sh, [[PROMPT, (cmd, T_FG)]], [PROMPT], "ssh-copy-id hpc-gpu")
add(dict(sh, shell=hist + [[("", T_FG)]], cursor=False), 500)
hist = hist + out(["The authenticity of host 'login.hpc.example.edu'", "can't be established.",
                   "ED25519 key fingerprint is SHA256:k3Jx9ZtQ0bWv7rL2…"])
ask = [("Are you sure you want to continue connecting", T_FG)]
yn = [("(yes/no/[fingerprint])? ", T_FG)]
yes = dict(sh, cap="5. First time only: answer yes to trust the host key (DirAI can't answer it)")
add(dict(yes, shell=hist + [ask, yn]), 2200)
hist = typed(yes, hist + [ask], yn, "yes", step=1, ms=180, col=T_YEL)
add(dict(yes, shell=hist), 600)
pw = dict(sh, cap="5. Type your password one last time: from now on the key logs you in")
hist = hist + [[("you@login.hpc.example.edu's password: ", T_FG)]]
add(dict(pw, shell=hist), 1800)
hist = hist + out(["", "Number of key(s) added: 1"], T_FG)
add(dict(pw, shell=hist + [[PROMPT]]), 1600)
# step 6: check it the way DirAI logs in: no questions at all now
chk = "ssh -o BatchMode=yes hpc-gpu hostname"
sh = dict(base, hint=None, cap="6. Check: now it logs in without asking anything, as DirAI's ssh must")
hist = typed(sh, hist, [PROMPT], chk)        # below the ssh-copy-id lines, so the "yes" stays in view
add(dict(sh, shell=hist + [[("", T_FG)]], cursor=False), 500)
hist = hist + [[("login1", T_FG)]]
add(dict(sh, shell=hist + [[PROMPT]]), 1500)
add(dict(sh, shell=hist + [[PROMPT]], cap="Done in the terminal. Next: Connect it in the agent list"), 1500)
# ---- GIF 2, the browser only: the list redraws (every 10 s) and re-reads ~/.ssh/config: hpc-gpu is offered
PART = "connect"
after = dict(sh, shell=hist + [[PROMPT]], hosts=["hpc-gpu"], sel="hpc-gpu", hint=None,
             cap="7. The agent list re-reads ~/.ssh/config at every redraw (every 10 s)")
add(dict(after, hosts=[], sel=None, cap="7. In the agent list: no Host to Connect to yet"), 1500)
add(dict(after, note="redrawn"), 1200)
add(dict(after, mouse=(TW + 80, 252)), 400)
add(dict(after, mouse=(TW + 80, 268), open=True, hover="hpc-gpu", cap="7. hpc-gpu is now in the Connect dropdown"), 2000)
picked = dict(after, cap="8. Pick it and click Connect")
add(dict(picked, mouse=(TW + 80, 252)), 500)
add(dict(picked, mouse=(TW + 175, 252)), 800)
# connecting -> copying DirAI -> up
con = dict(picked, connected=["hpc-gpu"], sel=None, mouse=(TW + 175, 252))
add(dict(con, link="connecting", cap="9. DirAI logs in with ssh (key only, no prompts)"), 1500)
add(dict(con, link="updating", cap="9. No DirAI there yet: it copies itself over the same ssh link"), 2000)
add(dict(con, link="up", cap="10. Connected: hpc-gpu has its own box, linked from the laptop"), 3000)
# ---- GIF 3, the browser only. New tree… (web/agent_list.js newTree): a folder on hpc-gpu, made if missing;
# DirAI init + start there over ssh
PART = "newtree"
up = dict(con, link="up", mouse=(TW + 44, 352))
add(dict(up, mouse=(TW + 200, 470), cap="11. hpc-gpu is connected, with no DirAI tree there yet"), 1500)
add(dict(up, cap="11. New tree… starts a DirAI tree in a folder on hpc-gpu"), 700)
nt = dict(up, nt="open", mouse=(TW + 60, 376), cap="11. New tree… starts a DirAI tree in a folder on hpc-gpu")
add(nt, 900)
path = "~/proj/sim"
for i in range(1, len(path) + 1):
    add(dict(nt, path=path[:i], cap="11. Type the folder there (it is made if missing)"), 80)
nt = dict(nt, path=path)
add(dict(nt, mouse=(TW + 120, 404), cap="11. Node: empty = where ssh lands; a node name or --job for a compute node"), 2200)
add(dict(nt, mouse=(TW + 60, 428), cap="12. Init and start: DirAI init and DirAI start run there over ssh"), 900)
add(dict(up, nt="starting", path=path, mouse=(TW + 60, 428), cap="12. Init and start: DirAI init and DirAI start run there over ssh"), 1600)
add(dict(up, nt="alive", path=path, mouse=(TW + 200, 440),
         cap="13. The tree is up. Each folder in it with an index.html is an agent"), 2500)
add(dict(up, nt="alive", path=path, mouse=(TW + 102, 374),
         cap="13. Open shows its agent list, right here in your browser"), 2500)

for part, name in PARTS:
    fr = frames[part]
    imgs = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f, _ in fr]
    dest = os.path.join(HERE, name)
    imgs[0].save(dest, save_all=True, append_images=imgs[1:], duration=[ms for _, ms in fr], loop=0, optimize=True)
    print("wrote", dest, len(imgs), "frames,", sum(ms for _, ms in fr) / 1000.0, "s,", os.path.getsize(dest) // 1024, "KB")
# --frames term:3,connect:0,newtree:12: also save those frames as PNG in tmp/, to look at them
import sys
if "--frames" in sys.argv:
    os.makedirs(os.path.join(HERE, "tmp"), exist_ok=True)
    for k in sys.argv[sys.argv.index("--frames") + 1].split(","):
        part, i = k.split(":")
        frames[part][int(i)][0].save(os.path.join(HERE, "tmp", "frame_%s_%s.png" % (part, i)))
