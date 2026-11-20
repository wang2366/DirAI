// Figures that a page's own script adds as <img src="x.svg"> after the page arrived (a viewer building its
// figures from data): the server inlined only the <img>s written in index.html (svg_inline.py), so this
// swaps each added one for the same <svg>, fetched from /_dirai/svg, and its text selects and quotes too.
// Loaded on every agent page, for every visitor; it does nothing until a script adds an <img>.
(function () {
  "use strict";
  var n = 0;

  function swap(img) {
    var src = img.getAttribute("src") || "", u;
    if (img.hasAttribute("data-dirai-tried") || !/\.svg(?:[?#]|$)/i.test(src)) return;
    try { u = new URL(src, document.baseURI); } catch (e) { return; }
    if (u.origin !== location.origin) return;
    img.setAttribute("data-dirai-tried", "");     // once: one that stays a picture isn't asked for again
    var path;
    try { path = decodeURIComponent(u.pathname); } catch (e) { return; }
    fetch("/_dirai/svg?path=" + encodeURIComponent(path) + "&n=" + (++n))
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (text) {
        if (!text || !img.parentNode || img.getAttribute("src") !== src) return;
        var box = document.createElement("div");
        box.innerHTML = text;
        var svg = box.querySelector("svg");
        if (!svg) return;
        svg.setAttribute("data-dirai-src", src);  // panel.js: a selection in it quotes x.svg (relative to the page)
        var alt = img.getAttribute("alt"), width = img.getAttribute("width");
        if (alt) { svg.setAttribute("role", "img"); svg.setAttribute("aria-label", alt); }
        if (width) { svg.setAttribute("width", width); svg.removeAttribute("height"); }
        if (img.className) svg.setAttribute("class", img.className);
        if (img.getAttribute("style")) svg.setAttribute("style", img.getAttribute("style"));
        img.parentNode.replaceChild(svg, img);
      })
      .catch(function () {});
  }

  function scan(node) {
    if (node.nodeType !== 1) return;
    if (node.tagName === "IMG") swap(node);
    else if (node.querySelectorAll) Array.prototype.forEach.call(node.querySelectorAll("img"), swap);
  }

  // Only what is added or re-pointed from now on: the <img>s already in the page were sent by the server,
  // which inlined every one it could.
  new MutationObserver(function (records) {
    records.forEach(function (r) {
      if (r.type === "attributes") {
        if (r.target.tagName === "IMG") { r.target.removeAttribute("data-dirai-tried"); swap(r.target); }
      }
      else Array.prototype.forEach.call(r.addedNodes, scan);
    });
  }).observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ["src"]});
})();
