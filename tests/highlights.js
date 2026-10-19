// Browser check of the change marks (run by test_highlights.py): panel.js and files.js on a page with
// the /_review API mocked. Blocks/lines the latest run added or changed are yellow (.rv-changed), the
// ones it removed are shown, collapsed, in red (.rv-removed) where they were. Exits 1 on a failure.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const WEB = path.join(__dirname, "..", "web");

const OLD = `<html><body><h1>T</h1><p>keep one</p><p>gone A</p><p id="g">gone B</p>
<table><tr><td>r1</td></tr><tr><td>row gone</td></tr></table><p>edited old</p><p>keep two</p></body></html>`;
const NOW = `<html><body><h1>T</h1><p>keep one</p><table><tr><td>r1</td></tr></table><p>edited new</p>
<p>keep two</p><p>brand new</p>
<script src="/_review/panel.js" data-agent="a"></script><script src="/_review/files.js" data-agent="a"></script></body></html>`;
const file = text => ({files: [{name: "run.sh", text, size: text.length, mtime: 0}], other: [], dirs: [], more: 0});
let files = file("one\ntwo\nthree\nfour\nfive\n");

let failed = 0;
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failed++; };

(async () => {
  const browser = await chromium.launch(fs.existsSync("/opt/pw-browsers/chromium") ? {executablePath: "/opt/pw-browsers/chromium"} : {});
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => e.message === "Failed to fetch" || errors.push(e.message));   // the aborted requests below
  await page.route("**/*", r => {
    const u = new URL(r.request().url());
    if (u.pathname === "/") return r.fulfill({contentType: "text/html", body: NOW});
    const js = u.pathname.match(/^\/_review\/(panel|files)\.js$/);
    if (js) return r.fulfill({contentType: "text/javascript", body: fs.readFileSync(path.join(WEB, js[1] + ".js"), "utf8")});
    if (u.pathname === "/_review/prev") return r.fulfill({contentType: "text/html", body: OLD});
    if (u.pathname === "/_review/files") return r.fulfill({contentType: "application/json", body: JSON.stringify(files)});
    return r.abort();   // the thread's state, the CDN: not needed here
  });
  await page.goto("http://dirai.test/");
  await page.waitForSelector(".rv-removed");
  await page.waitForSelector("#dirai-files .f-line", {state: "attached"});

  // index.html: what's in the body, in order (the panel and the files section aside)
  const body = await page.evaluate(() => [...document.body.children]
    .filter(e => !/^(SCRIPT|STYLE)$/.test(e.tagName) && !/^(rv-|dirai-)/.test(e.id))
    .map(e => (e.classList.contains("rv-removed") ? "removed:" : e.classList.contains("rv-changed") ? "changed:" : "") +
      (e.classList.contains("rv-removed") ? [...e.lastChild.children].map(c => c.textContent).join("+") : e.textContent.trim())));
  check(JSON.stringify(body) === JSON.stringify(["T", "keep one", "removed:gone A+gone B", "r1", "removed:row gone+edited old",
    "changed:edited new", "keep two", "changed:brand new"]), "index.html: removed blocks where they were, changed ones yellow: " + JSON.stringify(body));
  check(await page.evaluate(() => [...document.querySelectorAll(".rv-removed")].every(d => !d.open)), "index.html: removed blocks collapsed");
  check(await page.evaluate(() => !document.querySelector(".rv-removed [id]")), "index.html: removed blocks carry no ids");
  check(await page.evaluate(() => getComputedStyle(document.querySelector(".rv-removed")).backgroundColor) === "rgba(217, 48, 37, 0.14)",
    "index.html: removed blocks are red");
  // the button sits in the panel, closed here
  check(await page.evaluate(() => document.getElementById("rv-hl").style.display === ""), "Hide changes button offered");
  await page.evaluate(() => document.getElementById("rv-hl").click());
  check(!(await page.isVisible(".rv-removed")), "Hide changes hides removed blocks");
  await page.evaluate(() => document.getElementById("rv-hl").click());
  check(await page.isVisible(".rv-removed"), "Show changes shows them again");

  // the folder's files: a run edits run.sh; the section reloads and marks what changed
  check(await page.evaluate(() => !document.querySelector("#dirai-files .rv-changed, #dirai-files .rv-removed")),
    "files: nothing marked before a run");
  files = file("zero\none\nfour\nFIVE\n");
  await page.evaluate(() => document.dispatchEvent(new Event("dirai:run-done")));
  await page.waitForSelector("#dirai-files .rv-removed", {state: "attached"});
  const lines = await page.evaluate(() => [...document.querySelector("#dirai-files .f-src").children].map(e =>
    e.classList.contains("rv-removed") ? "removed:" + [...e.querySelectorAll(".f-gone")].map(g => g.textContent).join("+")
    : (e.classList.contains("rv-changed") ? "changed:" : "") + e.dataset.line + ":" + e.textContent));
  check(JSON.stringify(lines) === JSON.stringify(["changed:1:zero", "2:one", "removed:two+three", "3:four",
    "removed:five", "changed:4:FIVE"]), "files: removed lines where they were, changed ones yellow: " + JSON.stringify(lines));
  check(await page.evaluate(() => [...document.querySelectorAll("#dirai-files .rv-removed")].every(d => !d.open &&
    d.querySelector("summary").textContent === `Removed (${d.querySelectorAll(".f-gone").length} line${d.querySelectorAll(".f-gone").length === 1 ? "" : "s"})`)),
    "files: removed lines collapsed, with their count");

  check(!errors.length, "no errors on the page: " + errors.join("; "));
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log("FAIL " + e.stack); process.exit(1); });
