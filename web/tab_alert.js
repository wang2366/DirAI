// The mark on the browser tab of an agent's page, injected by server.py before panel.js (owner only).
// diraiTabAlert(level): level "needs" shows a red dot icon, "unread" a blue one, "" takes it away.
// The icon is the whole mark: the tab's title is left as the page's own.
(function () {
  const COLOR = {needs: "#c62828", unread: "#0b63ce"};   // the "needs you" and "unread" badge colours
  let shown = "", link = null;
  // A cleared icon stays as a blank one: browsers differ on what they show after a page removes its icon link.
  function icon(level) {
    const c = document.createElement("canvas");
    c.width = c.height = 32;
    if (level) {
      const g = c.getContext("2d");
      g.fillStyle = COLOR[level];
      g.beginPath();
      g.arc(16, 16, 14, 0, 2 * Math.PI);
      g.fill();
    }
    return c.toDataURL("image/png");
  }
  window.diraiTabAlert = function (level) {
    level = COLOR[level] ? level : "";
    if (level === shown) return;
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = icon(level);
    shown = level;
  };
})();
