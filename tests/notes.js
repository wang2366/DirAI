// Browser check of the sticky notes (run by test_notes.py): panel.js on a page with the /_review API
// mocked. Each note's text gets a numbered mark (the right copy of a phrase that is there twice), a note
// whose text is gone is listed as moved, hovering a mark shows its note, Send notes puts the open notes
// in the box as chips, × leaves one out, and the box may be empty. Exits 1 on a failure.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const WEB = path.join(__dirname, "..", "web");

const PAGE = `<html><body><h1>T</h1><h2>Rates</h2><p>the rates agree to 1e-12 except deck 4.</p>
<p>Later: the rates agree <b>again</b> after the fix.</p><p>Open: new references.</p><div id="late">Loading…</div><div><span style="text-transform:uppercase">your call</span> keep master's columns</div>
<svg data-dirai-src="d.svg" width="300" height="40"><text x="5" y="20">S1:</text><text x="40" y="20">one team repo</text></svg>
<script>setTimeout(() => document.getElementById("late").innerHTML = "<table><tr><td style='user-select:none'>11</td><td>the first line of the late code block</td></tr>" +
  "<tr><td style='user-select:none'>12</td><td>the second line of the late code block</td></tr></table>", 500);</script>
<script src="/_review/panel.js" data-agent="a"></script></body></html>`;
const note = (id, n, text, extra) => Object.assign({id, n, text, before: "", after: "", heading: "Rates", note: "", state: "open"}, extra);
let notes = [
  note("n1", 1, "rates agree", {before: "Later:the", after: "againafter", note: "which decks?"}),   // the 2nd copy
  note("n2", 2, "except deck 4", {note: "why?", noanswer: true}),   // a run left it unanswered (E2a)
  note("n3", 3, "a sentence the agent rewrote"),
  note("n4", 4, "references", {state: "sent"}),
  // in content the page's own script builds after load, across a line number the selection doesn't hold
  note("n6", 6, "the first line of the late code block\nthe second line of the late code block", {state: "sent"}),
  // as selected: the label is capitalised by CSS; answered by the agent on the note (dirai_note.py --at)
  note("n7", 7, "YOUR CALL keep", {state: "done", answer: "kept master's columns",
    thread: [{who: "agent", text: "kept master's columns", time: "t", state: "done", at: "#late"}]}),
  // its text was replaced, the words around it are still there: pinned between them
  note("n8", 8, "the bug we had", {state: "done", before: "againafterthe", after: "fix."}),
  // on a diagram the server put inline (svg_inline.py)
  note("n9", 9, "one team repo", {state: "sent", file: "d.svg", svg: true, before: "S1:"}),
];
// a run's reply that had notes: the chat shows a pointer to them (E3a)
const thread = [{role: "claude", time: "2026-11-17 10:00", text: "Done.", notes_result: [{id: "n7", n: 7, state: "done"}, {id: "n2", n: 2, state: "open", noanswer: true}]}];
const state = () => ({status: "read", thread, denials: [], models: ["opus"], model: "opus", auto_compact_choices: [0],
                      auto_compact: 0, ui: 1, notes});
let replied = null;
let sent = null;

let failed = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch(fs.existsSync("/opt/pw-browsers/chromium") ? {executablePath: "/opt/pw-browsers/chromium"} : {});
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => e.message === "Failed to fetch" || errors.push(e.message));
  page.on("dialog", d => { errors.push("a browser dialog opened: " + d.message()); d.dismiss(); });
  await page.route("**/*", r => {
    const u = new URL(r.request().url()), json = o => r.fulfill({contentType: "application/json", body: JSON.stringify(o)});
    if (u.pathname === "/") return r.fulfill({contentType: "text/html", body: PAGE});
    if (u.pathname === "/_review/panel.js") return r.fulfill({contentType: "text/javascript", body: fs.readFileSync(path.join(WEB, "panel.js"), "utf8")});
    if (u.pathname === "/_review/state") return json(state());
    if (u.pathname === "/_review/notes") {
      const b = JSON.parse(r.request().postData());
      if (b.op === "add") notes.push(Object.assign(note("n5", 5, b.note.text), {before: b.note.before, after: b.note.after, note: b.note.note}));
      if (b.op === "reply") {
        replied = b;
        notes = notes.map(n => n.id !== b.id ? n : Object.assign({}, n, {state: "open", thread: (n.thread || []).concat([{who: "owner", text: b.text, time: "t"}])}));
      }
      return json({ok: true, notes});
    }
    if (u.pathname === "/_review/comment") { sent = JSON.parse(r.request().postData()); return json({ok: true}); }
    return r.abort();   // prev, CDN: not needed here
  });
  await page.goto("http://dirai.test/");
  await page.waitForSelector("mark.rv-note");

  const marks = await page.$$eval("mark.rv-note", ms => ms.map(m => ({id: m.dataset.note, n: m.dataset.n || "", text: m.textContent,
    p: m.closest("p").textContent.slice(0, 6), cls: m.className})));
  check(marks.some(m => m.id === "n1" && m.p === "Later:"), "note 1 sits on the second 'rates agree' (its neighbours)");
  check(!marks.some(m => m.id === "n1" && m.p === "the ra"), "and not on the first");
  check(marks.filter(m => m.id === "n2").map(m => m.text).join("") === "except deck 4", "note 2 marks exactly its text");
  check(marks.some(m => m.id === "n2" && m.n === "2" && /rv-nend/.test(m.cls)), "its last mark carries the number");
  check(marks.some(m => m.id === "n4" && /sent/.test(m.cls)), "a sent note is marked as sent");
  const text = await page.$eval("body", b => [...b.querySelectorAll("p")].map(p => p.textContent).join("|"));
  check(text === "the rates agree to 1e-12 except deck 4.|Later: the rates agree again after the fix.|Open: new references.",
        "the page's text is unchanged");

  await page.click("#rv-btn");
  await page.click("#rv-notessum");
  await page.waitForSelector('mark.rv-note[data-note="n6"]', {timeout: 5000}).catch(() => null);
  const n6 = await page.$$eval('mark.rv-note[data-note="n6"]', ms => ms.map(m => m.textContent).join("|"));
  check(/^the first line/.test(n6) && /second line of the late code block$/.test(n6),
        "a note in content built later by the page's script, across an unselectable line number, is drawn");
  const list = await page.$$eval(".rv-nitem", rows => rows.map(r => r.textContent));
  check(await page.$$eval('mark.rv-note[data-note="n7"]', ms => ms.map(m => m.textContent).join("")) === "your callkeep",
        "a note on text CSS shows in capitals is drawn (case ignored)");
  check(list.length === 8 && /moved/.test(list[2]) && /moved/.test(list[7]) && !list.slice(3, 7).some(r => /moved/.test(r)), "the list has every note, the rewritten ones as moved");
  check(await page.$$eval('.rv-svgnote[data-note="n9"]', ts => ts.map(t => t.textContent).join("|")) === "one team repo" &&
        await page.$eval(".rv-svgpin", g => g.textContent) === "9", "a note on an inline diagram highlights its text there, with its number");
  await page.hover(".rv-svgpin");
  await page.waitForSelector("#rv-notepop", {state: "visible"});
  check(/Note 9/.test(await page.$eval("#rv-notepop", p => p.textContent)), "hovering it shows the note");
  await page.mouse.move(0, 0);
  check(await page.$eval("#rv-notelist", l => l.clientHeight < 100 && l.scrollHeight > l.clientHeight), "the list shows 4 rows, then scrolls");
  const pins = await page.$$eval("mark.rv-moved", ms => ms.map(m => m.dataset.note + "|" + m.dataset.where + "|" + m.parentElement.tagName + "|" +
    (m.nextSibling ? m.nextSibling.textContent.slice(0, 3) : "") + "|" + m.textContent));
  check(pins.includes("n8|where its text was|P|fix|"), "a rewritten note is pinned where its text was, holding no text " + pins.join(","));
  check(pins.some(p => /^n3\|under its heading\|H2\|/.test(p)), "with nothing around it left, under its heading");
  check(await page.$eval("#rv-notesend", b => b.textContent) === "Send 3 notes", "Send counts the open notes");

  await page.hover('mark.rv-note[data-note="n2"]');
  await page.waitForSelector("#rv-notepop", {state: "visible"});
  check(/Note 2/.test(await page.$eval("#rv-notepop", p => p.textContent)) &&
        /why\?/.test(await page.$eval("#rv-notepop", p => p.textContent)), "hover shows the note");

  await page.click("#rv-notesend");
  check((await page.$$(".rv-nchip")).length === 3, "Send notes: one chip per open note");
  await page.click('.rv-nchip button[data-unpin="n3"]');
  check((await page.$$(".rv-nchip")).length === 2, "× leaves one out");
  await page.click("#rv-text");
  await page.keyboard.press("Enter");
  for (let i = 0; i < 20 && !sent; i++) await page.waitForTimeout(100);
  check(sent && sent.text === "" && JSON.stringify(sent.notes) === '["n1","n2"]', "Enter with an empty box sends the two notes");
  check((await page.$$(".rv-nchip")).length === 0, "the chips are gone after sending");

  // a new note on a selection: + Sticky note keeps the words around it
  await page.evaluate(() => {
    const t = document.querySelectorAll("p")[2].firstChild, r = document.createRange();
    r.setStart(t, 6), r.setEnd(t, 9);    // "new"
    getSelection().removeAllRanges(), getSelection().addRange(r);
    document.dispatchEvent(new MouseEvent("mouseup"));
  });
  await page.waitForSelector("#rv-addnote", {state: "visible"});
  await page.click("#rv-addnote");
  await page.waitForSelector("#rv-notetext", {state: "visible"});
  check(await page.evaluate(() => document.activeElement && document.activeElement.id === "rv-notetext"), "the note box opens, focused");
  await page.keyboard.type("my new");
  await page.keyboard.press("Shift+Enter");   // a newline, not a save
  await page.keyboard.type("note");
  await page.keyboard.press("Control+Enter");
  await page.waitForSelector('mark.rv-note[data-note="n5"]');
  const n5 = notes.find(n => n.id === "n5");
  check(n5.text === "new" && n5.note === "my new\nnote" && /Open:$/.test(n5.before) && /^references/.test(n5.after),
        "+ Sticky note sends the text, the note typed in the box (two lines) and its neighbours");

  // edit from the pop-up: the box opens with the note in it, Esc leaves it unchanged
  await page.hover('mark.rv-note[data-note="n2"]');
  await page.click('#rv-notepop button[data-nop="edit"]');
  await page.waitForSelector("#rv-notetext", {state: "visible"});
  check(await page.$eval("#rv-notetext", t => t.value) === "why?", "edit opens the box with the note");
  await page.keyboard.press("Escape");
  check(!(await page.isVisible("#rv-notepop")), "Esc closes it");

  // the agent's answer on the note, with where it changed (E1b); the chat's pointer (E3a); a reply (E4/E5a)
  await page.mouse.move(0, 0);
  await page.hover('mark.rv-note[data-note="n7"]');
  await page.waitForSelector("#rv-notepop", {state: "visible"});
  const pop7 = await page.$eval("#rv-notepop", p => p.textContent);
  check(/Agent \(done\): kept master's columns/.test(pop7) && /changed here →/.test(pop7), "the pop-up shows the agent's answer and where");
  await page.click("#rv-notepop .rv-jump");
  check(!(await page.isVisible("#rv-notepop")), "changed here → goes to the place (pop-up closes)");
  const res = await page.$$eval(".rv-nres", as => as.map(a => a.textContent + "|" + a.className));
  check(res.length === 2 && /^✓7\|.*done/.test(res[0]) && /^\?2\|.*noanswer/.test(res[1]), "the chat shows Notes: ✓7 ?2 " + res.join(","));
  check(await page.$$eval(".rv-msg.rv-claude .rv-npoint", x => x.length) === 1, "the pointer sits in the reply");
  await page.click('.rv-nres[data-nres="n2"]');
  await page.waitForSelector("#rv-notepop", {state: "visible"});
  check(/Note 2 · no answer/.test(await page.$eval("#rv-notepop", p => p.textContent)), "a number opens its note's pop-up");
  await page.click('#rv-notepop button[data-nop="reply"]');
  await page.waitForSelector("#rv-notetext", {state: "visible"});
  await page.keyboard.type("and deck 5?");
  await page.keyboard.press("Control+Enter");
  for (let i = 0; i < 20 && !replied; i++) await page.waitForTimeout(100);
  check(replied && replied.id === "n2" && replied.text === "and deck 5?", "reply sends op reply with the text");
  await page.hover('mark.rv-note[data-note="n2"]');
  check(/You: and deck 5\?/.test(await page.$eval("#rv-notepop", p => p.textContent)), "the reply shows on the note");

  check(!errors.length, "no page errors " + errors.join("; "));
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log(e); process.exit(1); });
