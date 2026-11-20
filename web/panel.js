// The agent's panel, which server.py adds to every index.html it serves (owner only).
(function () {
  const AGENT = document.currentScript.dataset.agent;
  const api = (path, body) => fetch("/_review/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Review": "1"},
    body: JSON.stringify(Object.assign({agent: AGENT}, body)),
  }).then(r => r.json());

  const css = `
  #rv-btn{position:fixed;right:16px;bottom:16px;z-index:99999;padding:8px 14px;border-radius:20px;
    border:1px solid #888;background:#1d1d1f;color:#fff;font:600 14px system-ui;cursor:pointer}
  #rv-panel{position:fixed;right:16px;bottom:64px;z-index:99999;width:min(460px,calc(100vw - 32px));
    max-height:75vh;display:none;flex-direction:column;background:#fff;color:#1d1d1f;border:1px solid #bbb;
    border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.25);font:14px/1.45 system-ui}
  #rv-panel.open{display:flex}
  #rv-head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #ddd}
  #rv-head b{flex:1}
  .rv-pill{padding:2px 9px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
  .rv-pill.tog{cursor:pointer} .rv-pill.tog:hover{outline:2px solid #0003}
  .rv-working{background:#b26b00}.rv-queued{background:#7b1fa2}.rv-unread{background:#0b63ce}.rv-read{background:#2e7d32}
  .rv-closed{background:#666}.rv-none{background:#999}.rv-asking{background:#c62828}
  #rv-thread{overflow:auto;padding:10px 12px;flex:1}
  .rv-msg{margin:0 0 10px;padding:8px 10px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word}
  .rv-user{background:#eef4ff}.rv-claude{background:#f3f3f3}.rv-system{background:#fff6e0;font-size:13px}
  .rv-meta{font-size:11px;color:#777;margin-bottom:3px}
  .rv-ask{background:#fdecea;border:1px solid #e8b4ae;font-size:13px;white-space:normal}
  .rv-ask summary{cursor:pointer;word-break:break-all}
  .rv-ask pre{white-space:pre-wrap;word-break:break-all;margin:4px 0;font-size:12px;background:#fff;padding:4px;border:1px solid #eee;max-height:25vh;overflow:auto}
  .rv-ask .rv-row button.deny{border-color:#c62828;color:#c62828}
  .rv-said{font-size:12px;color:#555;margin-top:4px}
  .rv-inbox{background:#f5f8fe;border:1px dashed #0b63ce}.rv-inbox .rv-row{margin-top:4px}.rv-inbox button{font-size:12px;padding:2px 8px}
  #rv-denials{padding:8px 12px;border-top:1px solid #ddd;background:#fff8f0;display:none;flex-shrink:0}
  #rv-login{padding:8px 12px;border-top:1px solid #ddd;background:#fdecea;display:none;flex-shrink:0;font:13px system-ui}
  #rv-login button{padding:5px 10px;border-radius:6px;border:1px solid #999;background:#fafafa;cursor:pointer;font:13px system-ui}
  #rv-login button.primary{background:#0b63ce;border-color:#0b63ce;color:#fff}
  #rv-login input{flex:1;min-width:0;padding:5px 8px;border:1px solid #999;border-radius:6px;font:13px ui-monospace,monospace}
  #rv-login .rv-meta{margin-top:4px}
  #rv-dlist{max-height:22vh;overflow:auto;margin:6px 0;padding-left:18px}
  #rv-dlist li{margin:3px 0;font-size:12.5px;word-break:break-all}
  #rv-dlist summary{cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #rv-dlist details[open] summary{white-space:normal}
  #rv-dlist pre{white-space:pre-wrap;margin:4px 0;font-size:12px;background:#fff;padding:4px;border:1px solid #eee}
  #rv-thread{min-height:80px}
  #rv-foot{flex-shrink:0}
  #rv-foot{padding:10px 12px;border-top:1px solid #ddd}
  #rv-text{width:100%;box-sizing:border-box;min-height:70px;font:14px system-ui;padding:6px}
  .rv-row{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
  .rv-row button,#rv-denials button{padding:5px 10px;border-radius:6px;border:1px solid #999;background:#fafafa;cursor:pointer;font:13px system-ui}
  @media (hover:hover) and (pointer:fine){#rv-save{display:none}}   /* Enter sends; touch screens keep the button */
  .rv-row button.primary{background:#0b63ce;color:#fff;border-color:#0b63ce}
  button:disabled{opacity:.5;cursor:default}
  #rv-ctx{font-size:12px;color:#777;white-space:nowrap}
  #rv-sedit{display:none;margin-top:6px;padding:8px;border-radius:6px;background:#f3f3f3;font-size:12.5px}
  .rv-srow{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap}
  .rv-srow>b{font-weight:normal;width:58px}
  #rv-skind button{padding:3px 10px;border-radius:12px;border:1px solid #0b63ce;background:#fff;color:#0b63ce;cursor:pointer;font:12.5px system-ui}
  #rv-sdays button{width:34px;padding:3px 0;border-radius:5px;border:1px solid #999;background:#fff;color:#1d1d1f;cursor:pointer;font:12.5px system-ui}
  #rv-skind button.on,#rv-sdays button.on{background:#0b63ce;color:#fff;border-color:#0b63ce}
  #rv-sedit input[type=date],#rv-sedit input[type=time]{font:13px system-ui;padding:2px 4px;border:1px solid #999;border-radius:4px}
  #rv-snext{color:#2e7d32;margin-bottom:6px} #rv-snext.err{color:#c62828}
  #rv-stext{width:100%;box-sizing:border-box;min-height:56px;font:13px system-ui;padding:5px;margin-bottom:6px}
  #rv-sedit label{display:block;cursor:pointer}
  #rv-slist{margin-top:6px;font-size:12.5px}
  .rv-shead{font-weight:600;color:#555}
  .rv-sitem{display:flex;gap:6px;align-items:baseline;margin-top:3px}
  .rv-sitem b{white-space:nowrap} .rv-sitem i{color:#777;font-style:normal;white-space:nowrap}
  .rv-sitem span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#555}
  .rv-sitem.paused{opacity:.55}
  .rv-sitem button{border:0;background:none;cursor:pointer;padding:0 2px;color:#0b63ce;font:12px system-ui}
  .rv-sitem button[data-op=delete]{color:#555;font-size:14px;line-height:1}
  #rv-colls{margin-top:6px;font-size:12.5px}
  #rv-colls summary{cursor:pointer;color:#555}
  #rv-colllist{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
  .rv-coll{display:inline-flex;align-items:center;gap:2px;padding:1px 4px 1px 8px;border-radius:10px;background:#eef4ff;max-width:100%}
  .rv-coll a{color:#0b63ce;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .rv-coll.gone a{color:#999;text-decoration:line-through}
  .rv-coll button{border:0;background:none;cursor:pointer;font-size:14px;line-height:1;padding:0 2px;color:#555}
  .rv-coll button.rv-cname{font:12.5px system-ui;color:#1b7a3a;padding:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .rv-coll.read{background:#e6f4ea} .rv-coll.own{background:#fde4e1} .rv-coll.own button.rv-cname{color:#b3261e}
  .rv-coll.all{background:#a50e0e} .rv-coll.all button,.rv-coll.all a{color:#fff}
  .rv-coll.gone button.rv-cname{color:#999;text-decoration:line-through}
  .rv-hit{display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid #eee}
  .rv-hit .rv-hitx{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .rv-hit i{color:#777}
  .rv-hit button{flex:none;white-space:nowrap}
  #rv-colllink{flex:1;min-width:0;font:13px system-ui;padding:4px 6px;border:1px solid #999;border-radius:6px}
  #rv-model,#rv-autocompact{font:12px system-ui;padding:1px 2px;border:1px solid #bbb;border-radius:6px;background:#fff;color:#1d1d1f;text-overflow:ellipsis}
  #rv-model{width:6rem} #rv-autocompact{width:9rem}   /* fixed, so a long model name does not move the header; the opened list fits its text */
  #rv-close.on{background:#dcfce7;border-color:#2e7d32;color:#2e7d32}
  #rv-ctx.warn{color:#b26b00;font-weight:600} #rv-ctx.high{color:#c62828;font-weight:600}
  #rv-stale{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#ffe0e0;font-size:12.5px}
  #rv-cardnote{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#ffe0e0;font-size:12.5px}
  #rv-ctxnote{display:none;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#fff6e0;font-size:12.5px}
  #rv-ctxnote summary{cursor:pointer;font-weight:600} #rv-ctxnote[open] summary{margin-bottom:4px}
  #rv-chip{display:none;align-items:flex-start;gap:6px;margin:0 0 6px;padding:5px 8px;border-radius:6px;background:#eef4ff;font-size:12.5px}
  #rv-chip details,.rv-sel{flex:1;min-width:0}
  #rv-chip summary,.rv-sel summary{cursor:pointer;color:#0b63ce;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #rv-chip details[open] summary,.rv-sel[open] summary{white-space:normal}
  #rv-files{display:none;flex-wrap:wrap;gap:4px;margin:0 0 6px}
  .rv-file{display:inline-flex;align-items:center;gap:4px;max-width:100%;padding:2px 4px 2px 8px;border-radius:10px;background:#eef4ff;font-size:12.5px}
  .rv-file span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap} .rv-file i{color:#777;font-style:normal;white-space:nowrap}
  .rv-file.up{opacity:.6}
  .rv-file button{border:0;background:none;cursor:pointer;font-size:14px;line-height:1;padding:0 2px;color:#555}
  #rv-panel.rv-dragging{outline:3px dashed #0b63ce;outline-offset:-3px}
  #rv-panel.rv-dragging #rv-foot::before{content:"Drop to attach";display:block;margin:0 0 6px;padding:6px 8px;border-radius:6px;background:#eef4ff;color:#0b63ce;font-weight:600;text-align:center}
  #rv-unsel{border:0;background:none;cursor:pointer;font-size:15px;line-height:1;padding:0 2px;color:#555}
  .rv-quote{margin:4px 0 2px;padding:4px 8px;border-left:3px solid #9bb8e8;background:#fff;color:#333;
    white-space:pre-wrap;max-height:30vh;overflow:auto;font-size:12.5px}
  .rv-sel{margin:0 0 6px;font-size:12.5px}
  #rv-ask{position:absolute;z-index:99999;display:none;padding:3px 9px;border-radius:12px;border:1px solid #0b63ce;
    background:#0b63ce;color:#fff;font:600 12px system-ui;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2)}
  .rv-changed{background:rgba(255,213,0,.28)!important;box-shadow:0 0 0 3px rgba(255,213,0,.28)}
  body.rv-nohl .rv-changed{background:none!important;box-shadow:none}
  .rv-removed{margin:4px 0;padding:2px 8px;border-left:3px solid #d93025;background:rgba(217,48,37,.14)}
  .rv-removed>summary{cursor:pointer;color:#c5221f;font:600 12px system-ui}
  #rv-perms{margin-top:6px;font-size:.9em}
  #rv-perms summary{cursor:pointer;opacity:.75}
  #rv-perms ul{margin:4px 0;padding-left:20px}
  #rv-perms li{word-break:break-all}
  #rv-perms i{opacity:.75}
  #rv-perms li.unusable code{opacity:.5}
  #rv-perms button{border:0;background:none;cursor:pointer;font-size:14px;line-height:1;padding:0 4px;color:#555}
  .rv-ins{background:rgba(255,213,0,.6);border-radius:2px;box-shadow:0 0 0 1px rgba(255,213,0,.6)}
  .rv-del{color:#c5221f;background:rgba(217,48,37,.12);text-decoration:line-through;margin:0 .15em;user-select:none}
  body.rv-nohl .rv-ins{background:none;box-shadow:none} body.rv-nohl .rv-del{display:none}
  body.rv-nohl .rv-removed{display:none}
  .rv-undo{position:absolute;z-index:99990;padding:1px 9px;border:1px solid #b08900;border-radius:11px;background:#ffe57a;
    color:#4d3b00;font:600 12.5px/18px system-ui;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.3)}
  .rv-undo:hover{filter:brightness(1.06)} .rv-undo:disabled{cursor:default;opacity:.45}
  .rv-redo{border-color:#0b63ce;background:#0b63ce;color:#fff}
  .rv-undone{outline:2px dashed #0b63ce;outline-offset:3px}
  body.rv-nohl .rv-undo{display:none} body.rv-nohl .rv-undone{outline:none}
  .rv-clip{max-height:11.6em;overflow:hidden;-webkit-mask-image:linear-gradient(#000 70%,transparent);mask-image:linear-gradient(#000 70%,transparent)}
  .rv-more{display:block;margin-top:4px;padding:0;border:0;background:none;color:#0b63ce;cursor:pointer;font:600 12px system-ui}
  .rv-jump{color:#0b63ce;cursor:pointer;text-decoration:underline}
  .rv-jump.rv-broken{color:inherit;cursor:help;text-decoration:underline dotted} .rv-nres.rv-broken{opacity:.45;text-decoration:line-through;cursor:help}
  @keyframes rv-flash{0%,40%{outline-color:#0b63ce}100%{outline-color:transparent}}
  .rv-flash{outline:3px solid transparent;outline-offset:3px;animation:rv-flash 1.8s ease-out}
  #rv-toast{position:fixed;right:110px;bottom:16px;z-index:99999;display:none;align-items:center;gap:8px;padding:6px 10px;
    border-radius:8px;background:#1d1d1f;color:#fff;font:13px system-ui;box-shadow:0 4px 14px rgba(0,0,0,.3)}
  #rv-toast button{border:0;background:none;color:#8ab4f8;cursor:pointer;font:600 13px system-ui;padding:0 2px}
  #rv-toast button.x{color:#bbb;font-size:16px;line-height:1}
  #rv-addnote{position:absolute;z-index:99999;display:none;padding:3px 9px;border-radius:12px;border:1px solid #e0b400;
    background:#fff3b0;color:#4d3b00;font:600 12px system-ui;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2)}
  mark.rv-note{background:rgba(255,213,0,.42);color:inherit;border-bottom:2px solid #e0b400;border-radius:2px;cursor:pointer;padding:0}
  mark.rv-note.sent{background:rgba(11,99,206,.13);border-bottom-color:#0b63ce}
  mark.rv-note.done{background:rgba(0,0,0,.06);border-bottom-color:#bbb}
  mark.rv-note.rv-nend::after{content:attr(data-n);display:inline-block;margin-left:2px;min-width:14px;height:14px;padding:0 3px;box-sizing:border-box;
    border-radius:7px;background:#e0b400;color:#fff;font:700 10px/14px system-ui;text-align:center;vertical-align:super}
  mark.rv-note.sent.rv-nend::after{background:#0b63ce} mark.rv-note.done.rv-nend::after{background:#999;content:"✓" attr(data-n)}
  #rv-notepop{position:absolute;z-index:99999;display:none;max-width:320px;padding:6px 9px;border:1px solid #e0b400;border-radius:6px;
    background:#fff9d6;color:#1d1d1f;font:13px/1.4 system-ui;box-shadow:0 4px 14px rgba(0,0,0,.2);white-space:pre-wrap;word-wrap:break-word}
  #rv-notepop .rv-meta{white-space:normal} #rv-notepop .rv-nans{margin-top:4px;padding-top:4px;border-top:1px dashed #e0b400;color:#555}
  #rv-notepop .rv-row button{font-size:12px;padding:2px 8px}
  #rv-notepop{max-height:60vh;overflow:auto} #rv-notepop .rv-nans.owner{color:#0b63ce}
  .rv-svgnote{paint-order:stroke;stroke:rgba(255,213,0,.75);stroke-width:5px;stroke-linejoin:round;cursor:pointer}
  .rv-svgnote.sent{stroke:rgba(11,99,206,.25)} .rv-svgnote.done{stroke:rgba(0,0,0,.12)} .rv-svgnote.noanswer{stroke:rgba(198,40,40,.3)}
  .rv-svgpin{cursor:pointer;user-select:none} .rv-svgpin rect{fill:#e0b400} .rv-svgpin text{fill:#fff;stroke:none;font:bold 10px system-ui}
  .rv-svgpin.sent rect{fill:#0b63ce} .rv-svgpin.done rect{fill:#999} .rv-svgpin.noanswer rect{fill:#c62828}
  mark.rv-note.rv-moved{background:none;border-bottom:none} mark.rv-note.rv-moved::after{outline:1px dashed #555;outline-offset:1px}
  mark.rv-note.noanswer{border-bottom-color:#c62828} mark.rv-note.noanswer.rv-nend::after{background:#c62828}
  .rv-npoint{margin-bottom:4px} .rv-nres{display:inline-block;margin:0 2px;padding:0 5px;border-radius:8px;cursor:pointer;
    font:600 12px system-ui;text-decoration:none;background:#fff3b0;color:#7a6200;border:1px solid #e0b400}
  .rv-nres.done{background:#eee;color:#1a7f37;border-color:#bbb} .rv-nres.noanswer{background:#fdecea;color:#c62828;border-color:#c62828}
  #rv-notepop textarea{display:block;box-sizing:border-box;width:300px;max-width:100%;min-height:5em;margin:4px 0;padding:4px 6px;
    font:13px/1.4 system-ui,sans-serif;border:1px solid #e0b400;border-radius:4px;resize:vertical}
  #rv-notes{margin-top:6px;font-size:12.5px} #rv-notes summary{cursor:pointer;color:#555}
  .rv-nitem{display:flex;gap:6px;align-items:baseline;margin-top:3px;line-height:20px}
  #rv-notelist{max-height:92px;overflow-y:auto;overscroll-behavior:contain}   /* 4 rows, then it scrolls */
  .rv-nitem b{min-width:16px;text-align:center;border-radius:8px;background:#e0b400;color:#fff;font-size:11px}
  .rv-nitem.sent b{background:#0b63ce} .rv-nitem.done{opacity:.55} .rv-nitem.done b{background:#999}
  .rv-nitem span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
  .rv-nitem i{color:#777;font-style:normal;white-space:nowrap}
  .rv-nitem button{border:0;background:none;cursor:pointer;padding:0 2px;color:#0b63ce;font:12px system-ui}
  .rv-nitem button[data-nop=delete]{color:#555;font-size:14px;line-height:1}
  #rv-notechips{display:none;flex-wrap:wrap;gap:4px;margin:0 0 6px}
  .rv-nchip{display:inline-flex;align-items:center;gap:4px;max-width:100%;padding:2px 4px 2px 8px;border-radius:10px;background:#fff3b0;font-size:12.5px}
  .rv-nchip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .rv-nchip button{border:0;background:none;cursor:pointer;font-size:14px;line-height:1;padding:0 2px;color:#555}`;
  document.head.insertAdjacentHTML("beforeend", "<style>" + css + "</style>");
  document.body.insertAdjacentHTML("beforeend", `
  <button id="rv-btn">Chat</button><button id="rv-ask">Ask the agent about this</button><button id="rv-addnote" title="Leave a note on this text; send your notes together later (Chat: Sticky notes)">+ Sticky note</button><div id="rv-notepop"></div>
  <div id="rv-toast"><span id="rv-toastmsg"></span><button id="rv-toastgo"></button><button id="rv-toastx" class="x" title="Close">&times;</button></div>
  <div id="rv-panel">
    <div id="rv-head"><b>Chat</b><span id="rv-ctx" title="tokens in this session's context, resent with every message"></span><select id="rv-model" title="Model for this agent's next messages (Sonnet uses fewer of your Claude limits than Opus; the local gpt-oss and GenAI Studio models use none, but are weaker)"></select><select id="rv-autocompact" title="Auto compact: when a run ends with the context at this size or more, the agent compacts the conversation by itself"></select><span id="rv-status" class="rv-pill rv-none">none</span>
      <button id="rv-x" style="border:0;background:none;font-size:18px;cursor:pointer">&times;</button></div>
    <div id="rv-thread"></div>
    <div id="rv-denials"><b>Claude was blocked from:</b><ul id="rv-dlist"></ul>
      <div class="rv-row"><button id="rv-once" title="For the retry this starts only">Allow once</button><button id="rv-always" title="For every later run of this agent, and of the agents that list it as a colleague">Always allow</button><button id="rv-dismiss" title="Clear this list without granting anything (the agent list stops saying needs you)">Dismiss</button></div></div>
    <div id="rv-login"><b id="rv-lhead"></b><div id="rv-lbody"></div></div>
    <div id="rv-foot"><div id="rv-stale">DirAI was updated. Send or clear your message and this tab reloads, or reload it now.</div><details id="rv-ctxnote"><summary id="rv-ctxsum"></summary><span id="rv-ctxbody"></span></details><div id="rv-cardnote"></div><div id="rv-chip"></div><div id="rv-notechips"></div><div id="rv-files"></div><textarea id="rv-text" placeholder="Message this agent... (Enter to send, Shift+Enter for a new line, paste or drop files to attach)"></textarea>
      <div class="rv-row"><button id="rv-save" class="primary">Send</button><button id="rv-attach" title="Attach files (or drop them on the page, or paste an image into the box)">📎</button><input type="file" id="rv-pick" multiple hidden>
        <button id="rv-sched" title="Send a message to this agent at a time you pick, once or repeating (it waits if the agent is busy then)">Schedule…</button>
        <button id="rv-new" title="Your next message starts a fresh session (the agent re-reads its index.html and the last few messages)">New chat</button><button id="rv-close">TaskDone</button><button id="rv-cancel" style="display:none" title="Stop this run (or take the message out of the queue). The session is kept: change the model if you like, then send another message to continue.">Cancel</button><button id="rv-hl" style="display:none" title="Parts of index.html the agent added or changed in its latest run that edited it">Hide changes</button></div>
      <div id="rv-sedit">
        <div class="rv-srow"><b>Send</b><span id="rv-skind"><button data-kind="once">Once</button> <button data-kind="daily">Daily</button> <button data-kind="weekly">Weekly</button> <button data-kind="hourly">Every hour</button></span></div>
        <div class="rv-srow" id="rv-sdaterow"><b>on</b><input type="date" id="rv-sdate"></div>
        <div class="rv-srow" id="rv-sdaysrow"><b>on</b><span id="rv-sdays">${["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d, i) => `<button data-day="${i}">${d}</button>`).join(" ")}</span></div>
        <div class="rv-srow"><b>at</b><input type="time" id="rv-stime"><span id="rv-stz" class="rv-meta"></span></div>
        <div id="rv-snext"></div>
        <textarea id="rv-stext" placeholder="The message to send"></textarea>
        <div class="rv-srow"><b>Each run</b><span><label><input type="radio" name="rv-ssess" value="fresh"> fresh chat (re-reads index.html)</label><label><input type="radio" name="rv-ssess" value="continue"> continue this chat</label></span></div>
        <div class="rv-row"><button id="rv-ssave" class="primary">Save schedule</button><button id="rv-scancel">Cancel</button></div></div>
      <div id="rv-slist"></div>
      <details id="rv-notes"><summary id="rv-notessum" title="Notes you left on text of this page (select text, then + Sticky note). Send puts the open ones in your next message">Sticky notes</summary>
        <div id="rv-notelist"></div>
        <div class="rv-row"><button id="rv-notesend" class="primary" title="Put the open notes in the message box (× on one leaves it out), then send">Send notes</button><button id="rv-noteclear" title="Delete the done notes and the agent's answers on them (they stay until you do)">Clear done</button></div></details>
      <details id="rv-colls"><summary id="rv-collsum" title="Other agents this one may read (read-only) and whose granted permissions it shares; their summary cards go in its instructions">Colleagues</summary>
        <div id="rv-colllist"></div>
        <div class="rv-row"><input id="rv-colllink" placeholder="Paste a link to another agent's page, or type a keyword"><button id="rv-colladd">Add</button></div>
        <div id="rv-collres"></div></details></div>
  </div>`);

  const $ = id => document.getElementById(id);
  let state = null, timer = null;
  let files = [];   // dropped on the panel for the next message: {name, size, path (once saved in pasted/)}
  let notePins = [];   // ids of the sticky notes that go with the next message (Send notes; × on a chip drops one)
  // redraw the thread only when it changed, and keep the reader's scroll position;
  // jump to the newest message only on first load and after the owner sends something;
  // a reply that arrives while the reader is at the bottom shows from its first line
  let shownThread = null, scrollToEnd = true, keepTop = null;
  const atEnd = box => box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const LABEL = {closed: "TaskDone"};   // shown name for a stored status
  const esc = s => s.replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
  const attr = s => esc(s).replace(/"/g, "&quot;");   // for a value in an attribute

  // An open panel stays open across a reload, at the same place in the thread
  function keepOpen() {
    try {
      if (!$("rv-panel").classList.contains("open")) return;
      sessionStorage.setItem("rv-open", "1");
      if (!atEnd($("rv-thread"))) sessionStorage.setItem("rv-top", $("rv-thread").scrollTop);
    } catch (e) {}
  }
  // The scripts changed on the server since this tab loaded (st.ui): reload, unless that would
  // throw away a message being typed; then just say so. An open panel stays open.
  function stale() {
    if (!$("rv-text").value.trim() && !schedEditing() && !files.length && !notePins.length) {
      keepOpen();
      return location.reload();
    }
    $("rv-stale").style.display = "block";
    clearTimeout(timer);
    timer = setTimeout(refresh, 4000);
  }
  function render(st) {
    if (render.ui === undefined) render.ui = st.ui;
    else if (st.ui !== render.ui) return stale();
    state = st;
    const s = st.status;
    const asking = !!st.asking;   // a run waits for the owner's answer in the thread
    const needs = asking || st.denials.length > 0;   // or refused actions wait for a decision (#rv-denials), as in the agent list
    $("rv-status").textContent = needs ? "needs you" : LABEL[s] || s;
    $("rv-status").className = "rv-pill rv-" + (needs ? "asking" : s);
    $("rv-close").textContent = s === "closed" ? "TaskDone ✓" : "TaskDone";   // pressed once closed; a click then makes it read
    $("rv-close").classList.toggle("on", s === "closed");
    $("rv-btn").textContent = "Chat" + (needs ? " ❗" : s === "unread" ? " •" : s === "working" || s === "queued" ? " …" : "");
    diraiTabAlert(needs ? "needs" : s === "unread" ? "unread" : "");   // a red / blue dot as the tab's icon (tab_alert.js)
    if (asking && !render.asking) scrollToEnd = true;   // bring a new prompt into view
    // a run ended (a new reply, also before any SLURM jobs it left are done): files.js reloads the folder
    const last = (st.thread.filter(m => m.role === "claude").pop() || {}).time || "";
    const newReply = render.lastReply !== undefined && last !== render.lastReply;
    if (newReply) document.dispatchEvent(new Event("dirai:run-done"));
    render.lastReply = last;
    render.asking = asking;
    // waiting on SLURM jobs still counts as working, but a new comment can go in
    const watching = (st.watching || []).length > 0;
    const busy = (s === "working" || s === "queued") && !watching;
    const inbox = st.inbox || [];   // messages sent while it was busy (agents.py INBOX_MAX)
    if (inbox.length) $("rv-status").textContent += " · " + inbox.length + " queued";
    const threadKey = JSON.stringify([st.thread, inbox, busy]);
    if (threadKey !== shownThread) {
      const box = $("rv-thread"), top = box.scrollTop, wasAtEnd = atEnd(box);
      const opened = [...box.querySelectorAll(".rv-sel")].map(d => d.open);   // keep expanded quotes expanded
      box.innerHTML = (st.thread.map(m => m.role === "ask" ? askHtml(m) :
        `<div class="rv-msg rv-${m.role}"><div class="rv-meta">${m.role}${m.scheduled ? " (scheduled" + (/^(hour|day|week)$/.test(m.scheduled) ? ", every " : ": ") + m.scheduled + ")" : ""}${m.later ? " (sent later, held for " + m.later + ")" : ""}${m.model ? " (" + m.model + ")" : ""} · ${m.time}${m.cost != null ? " · $" + m.cost : ""}</div>${m.selection ? selHtml(m.selection) : ""}${m.notes ? notesHtml(m.notes) : ""}${m.notes_result ? notesResultHtml(m.notes_result) : ""}${m.role === "claude" ? replyHtml(m) : esc(m.text)}</div>`
      ).join("") || (inbox.length ? "" : '<div class="rv-meta">No comments yet.</div>')) + inboxHtml(inbox, busy);
      box.querySelectorAll(".rv-sel").forEach((d, i) => d.open = !!opened[i]);
      markBroken(box);
      shownThread = threadKey;
      const reply = newReply && wasAtEnd && [...box.querySelectorAll(".rv-claude")].pop();
      if (!$("rv-panel").classList.contains("open")) scrollToEnd = true;        // hidden: scroll when it opens
      else if (keepTop !== null) { box.scrollTop = keepTop; keepTop = null; scrollToEnd = false; }   // back from a reload
      else if (scrollToEnd) { box.scrollTop = box.scrollHeight; scrollToEnd = false; }
      else if (reply) box.scrollTop += reply.getBoundingClientRect().top - box.getBoundingClientRect().top;
      else box.scrollTop = top;
    }
    const sel = $("rv-model");
    if (sel.dataset.models !== st.models.join())
      sel.dataset.models = st.models.join(), sel.innerHTML = st.models.map(m => `<option value="${m}">${(st.model_labels || {})[m] || m[0].toUpperCase() + m.slice(1)}</option>`).join("");
    if (document.activeElement !== sel) sel.value = st.model;
    if (!sel.dataset.base) sel.dataset.base = sel.title;   // the box is fixed-width, so the full name goes in the tooltip
    sel.title = sel.dataset.base + " Now: " + (sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "");
    sel.disabled = busy;   // takes effect from the next message
    const ac = $("rv-autocompact"), choices = st.auto_compact_choices || [];
    if (ac.dataset.choices !== choices.join())
      ac.dataset.choices = choices.join(), ac.innerHTML = choices.map(n => `<option value="${n}">${n ? "Auto compact " + n / 1000 + "K" : "Auto compact off"}</option>`).join("") + '<option value="now">Compact now</option>';
    if (document.activeElement !== ac) ac.value = st.auto_compact;
    ac.querySelector('option[value="now"]').disabled = busy || !st.session_id;   // as the old Compact button
    // this agent's scheduled messages, soonest first (the server sorts them and writes their times)
    const sch = st.schedules || [], schKey = JSON.stringify(sch);
    if (schKey !== render.shownSched) render.shownSched = schKey, $("rv-slist").innerHTML = sch.length ?
      `<div class="rv-shead">Scheduled for this agent (${sch.length})</div>` + sch.map(s =>
        `<div class="rv-sitem${s.paused ? " paused" : ""}" title="${attr(s.text)}"><b>${esc(s.when)}</b>` +
        `<i>${esc(s.label)}${s.paused ? " · paused" : ""}</i><span>${s.selection ? "📎 " : ""}${esc(s.text.replace(/\s+/g, " "))}</span>` +
        `<button data-op="edit" data-sid="${attr(s.id)}">edit</button>` +
        `<button data-op="${s.paused ? "resume" : "pause"}" data-sid="${attr(s.id)}">${s.paused ? "resume" : "pause"}</button>` +
        `<button data-op="delete" data-sid="${attr(s.id)}" title="Delete">&times;</button></div>`).join("") : "";
    $("rv-text").placeholder = busy ? "The agent is working: your message waits and goes when this run ends (Enter to queue)"
      : "Message this agent... (Enter to send, Shift+Enter for a new line, paste or drop files to attach)";
    $("rv-close").disabled = busy || watching;
    const tog = !needs && (s === "unread" || s === "read") && !busy && !watching;   // the pill itself switches read / unread
    $("rv-status").classList.toggle("tog", tog);
    $("rv-status").title = tog ? "click: mark read / unread" : "";
    $("rv-new").disabled = busy || !st.session_id;   // nothing to start over from yet
    $("rv-cancel").style.display = busy || watching ? "" : "none";
    document.querySelectorAll(".rv-undo").forEach(b => b.disabled = busy);
    const ctx = st.context, level = ctx == null ? "" : ctx >= st.context_high ? "high" : ctx >= st.context_warn ? "warn" : "";
    $("rv-ctx").textContent = ctx == null ? "" : "context " + Math.round(ctx / 1000) + "K";
    $("rv-ctx").className = level;
    $("rv-ctxnote").style.display = level && !busy ? "block" : "none";
    if (level) $("rv-ctxsum").textContent = `Long conversation (${Math.round(ctx / 1000)}K tokens): ` + (st.auto_compact ? `auto compact at ${st.auto_compact / 1000}K, or New chat` : "Compact now (Auto compact menu) or New chat"),
      $("rv-ctxbody").textContent = `This conversation is ${Math.round(ctx / 1000)}K tokens, and every message resends all of it, ` +
      `which uses up your Claude limits faster${level === "high" ? " (a lot faster at this size)" : ""}. ` +
      "Compact summarizes it and keeps the session; New chat starts over from index.html and the last few messages.";
    const card = st.card || [];   // the summary card in index.html (dirai_card.py), checked by the server
    $("rv-cardnote").style.display = card.length && !busy ? "block" : "none";
    $("rv-cardnote").textContent = "Summary card: " + card.join("; ") + ". Ask the agent to fix it.";
    // colleagues: a chip per agent this one may read; a click on its name moves it to the next state
    // (green read → light red ✎ edit its own files → dark red ✎✎ edit everything, asked first → read),
    // ↗ opens its page, ✕ removes it
    const colls = st.colleagues || [];
    $("rv-collsum").textContent = "Colleagues" + (colls.length ? " (" + colls.length + ")" : "");
    const collKey = JSON.stringify(colls);
    if (collKey !== render.shownColls) render.shownColls = collKey, $("rv-colllist").innerHTML = colls.map(c => {
      const mode = c.mode || "read", name = c.path.split("/").pop() || "top agent";
      return `<span class="rv-coll ${mode}${c.gone ? " gone" : ""}">` +
        `<button class="rv-cname" data-mode="${attr(c.path)}" data-next="${attr(c.next || "own")}" title="${attr(c.path || "the tree's top agent")}${c.gone ? " (gone)" : ""}: ` +
        `${COLL_SAYS[mode]}. Click: ${COLL_SAYS[c.next || "own"]} (from its next run)">${COLL_MARK[mode]}${esc(name)}</button>` +
        `<a href="${attr(c.url)}" title="Open its page">↗</a><button data-coll="${attr(c.path)}" title="Remove">&times;</button></span>`;
    }).join("");
    // the agent's own grants, collapsed at the end of its summary card (colleagues' are on their pages);
    // × removes one; the ones no later command can match (lines of inline scripts) come first, greyed.
    // A server started before grant_info existed sends just the rules, without the flags
    const perms = (st.grant_info || (st.grants || []).map(r => ({rule: r}))).slice()
        .sort((a, b) => !!b.unusable - !!a.unusable),
      cardEl = document.getElementById("dirai-card"), permKey = JSON.stringify(perms);
    if (cardEl && permKey !== render.shownPerms) {
      render.shownPerms = permKey;
      let box = $("rv-perms");
      if (!box) {
        box = document.createElement("details"), box.id = "rv-perms", cardEl.appendChild(box);
        box.addEventListener("click", e => {
          const b = e.target.closest("[data-ungrant]");
          if (b) b.disabled = true, post("ungrant", {rules: [b.dataset.ungrant]});
        });
      }
      const junk = perms.filter(p => p.unusable).length;
      box.innerHTML = `<summary title="What this agent was granted beyond the defaults and dirai.json (Always allow, folders named in messages)">` +
        `Permissions (${perms.length}${junk ? ", " + junk + " look unusable" : ""})</summary>` +
        (perms.length ? "<ul>" + perms.map(p => `<li${p.unusable ? ` class="unusable" title="Looks unusable: ${attr(p.unusable)}"` : ""}>` +
          `<code>${esc(p.rule)}</code>${p.denied ? " <i>always denied, has no effect</i>" : ""}` +
          `<button data-ungrant="${attr(p.rule)}" title="Remove (from the next run)">&times;</button></li>`).join("") + "</ul>"
          : "<i>none: only the defaults and dirai.json</i>");
    }
    const grantable = st.denials.filter(d => !d.blocked && !d.granted);
    // one line per denial; click to see the full command
    const denialKey = JSON.stringify(st.denials);   // same idea: don't collapse opened entries
    if (denialKey !== render.shownDenials) render.shownDenials = denialKey, $("rv-dlist").innerHTML = st.denials.map(d =>
      `<li><details><summary>${d.blocked ? '<i style="color:#a00">always blocked, run it yourself:</i> '
        : d.granted ? '<i style="color:#a00">already allowed, refused by a built-in safety check (shell constructs like $( ), loops or ..); ask the agent to do it with a script:</i> '
        : ""}${esc(d.text.slice(0, 120))}</summary>` +
      `<pre>${esc(d.text)}</pre>` + (d.blocked || d.granted ? "" : `<div class="rv-meta">Allow grants: ${d.rules.map(r => `<code>${esc(r)}</code>` +
        (d.keep && !d.keep.includes(r) ? " <i>(once only: can't recur)</i>" : "")).join(" ")}</div>`) +
      `</details></li>`).join("");
    $("rv-once").style.display = grantable.length ? "" : "none";
    // Always keeps only rules a later command may match: none left (an inline script's lines), no button
    $("rv-always").style.display = grantable.some(d => (d.keep || d.rules).length) ? "" : "none";
    $("rv-denials").style.display = st.denials.length && !busy ? "block" : "none";
    renderLogin(st.login);
    renderNotes(st.notes || []);
    clearTimeout(timer);
    const signingIn = st.login && st.login.proc && ["starting", "waiting"].includes(st.login.proc.state);
    if (signingIn) timer = setTimeout(refresh, 2000);    // the sign-in link, then the result
    else if (busy || watching) timer = setTimeout(refresh, watching ? 30000 : 4000);
    else timer = setTimeout(refresh, 60000);   // idle: a scheduled or SLURM wake-up run may start
  }
  // Claude runs on this server wait for an expired login (st.login): Log in here (`claude auth login` on
  // the server: open its link, sign in, paste the code the page shows) or Retry after logging in in a terminal.
  // Redrawn only when it changed, so a code being typed isn't wiped.
  function renderLogin(l) {
    const box = $("rv-login"), key = JSON.stringify(l);
    box.style.display = l ? "block" : "none";
    if (!l || key === renderLogin.shown) return;
    renderLogin.shown = key;
    const p = l.proc || {}, host = esc(l.host || "this machine");
    $("rv-lhead").textContent = l.held ? "Claude login expired on " + (l.host || "this machine") : "Logging in to Claude";
    let html = "";
    if (p.state === "starting") html = `<div class="rv-meta">Starting <code>claude auth login</code> on ${host}…</div>` +
      (p.output ? `<pre class="rv-meta">${esc(p.output)}</pre>` : "") + `<div class="rv-row"><button id="rv-lcancel">Cancel</button></div>`;
    else if (p.state === "waiting") html =
      (p.url ? `<div class="rv-row"><button id="rv-lopen" class="primary" data-url="${attr(p.url)}">1. Open the sign-in page</button></div>` : "") +
      `<div class="rv-row"><input id="rv-lcode" placeholder="2. Paste the code the page shows" autocomplete="off"><button id="rv-lsend" class="primary">Send</button><button id="rv-lcancel">Cancel</button></div>` +
      (p.message ? `<div class="rv-meta">${esc(p.message)}</div>` : "");
    else html =
      (p.state === "failed" ? `<div class="rv-meta">${esc(p.message || "Login failed.")}</div>` : "") +
      (p.state === "ok" ? `<div class="rv-meta">Logged in. Sending the waiting messages…</div>` : "") +
      `<div class="rv-row"><button id="rv-lstart" class="primary" title="Runs claude auth login on ${host}; you sign in in a new tab">Log in</button>` +
      `<button id="rv-lretry" title="Already logged in in a terminal (claude, then /login): send the waiting messages now">Retry now</button></div>` +
      `<div class="rv-meta">Or in a terminal on ${host}: <code>claude</code>, then <code>/login</code>. Waiting messages go by themselves within 30 s of a new login.` +
      (l.config_dir ? ` Claude's folder here: <code>${esc(l.config_dir)}</code>.` : "") + `</div>`;
    $("rv-lbody").innerHTML = html;
  }
  $("rv-login").addEventListener("click", e => {
    const id = e.target.id;
    if (id === "rv-lopen") window.open(e.target.dataset.url, "_blank", "noopener");
    else if (id === "rv-lstart") post("claude_login", {op: "start"});
    else if (id === "rv-lretry") post("claude_login", {op: "retry"});
    else if (id === "rv-lcancel") post("claude_login", {op: "cancel"});
    else if (id === "rv-lsend") post("claude_login", {op: "code", code: $("rv-lcode").value.trim()});
  });
  $("rv-login").addEventListener("keydown", e => {
    if (e.target.id === "rv-lcode" && e.key === "Enter") e.preventDefault(), $("rv-lsend").click();
  });
  // a permission prompt from the run (ask mode): Allow / Always allow / Deny while it waits
  const SAID = {allow: "✅ Allowed", always: "✅ Allowed, and always for this agent from now on", deny: "⛔ Denied",
    timeout: "⛔ Denied: no answer within the run's waiting limit", ended: "Not answered: the run ended",
    withdrawn: "Withdrawn by Claude"};
  const COLL_SAYS = {read: "read-only", own: "may edit its own files, not the agents inside it",
    all: "may edit everything in its folder"}, COLL_MARK = {read: "", own: "✎ ", all: "✎✎ "};
  function askHtml(m) {
    // once_only: some of it can't recur (a line of an inline script), so Always allow wouldn't keep it
    const always = (m.rules || []).length > 0;
    return `<div class="rv-msg rv-ask"><div class="rv-meta">Claude asks to use · ${m.time}</div>` +
      `<details><summary>${esc(m.text.slice(0, 200))}</summary><pre>${esc(m.detail || m.text)}</pre>` +
      (always ? `<div class="rv-meta">Always allow keeps: ${m.rules.map(r => `<code>${esc(r)}</code>`).join(" ")}</div>` : "") +
      (m.once_only ? `<div class="rv-meta">Not kept by Always (once only): ${esc(m.once_only)}</div>` : "") +
      `</details>` +
      (m.heredoc && !m.answer ? `<div class="rv-meta">An inline script: it asks every time. Deny tells the agent to write it to a file in its folder and run that.</div>` : "") +
      (m.answer ? `<div class="rv-said">${SAID[m.answer] || esc(m.answer)}</div>`
        : `<div class="rv-row" data-ask="${esc(m.id)}"><button data-choice="allow" class="primary">Allow</button>` +
          (always || !m.once_only ? `<button data-choice="always" title="Allow it, and keep the rule for this agent (and the agents that list it as a colleague)">Always allow</button>` : "") +
          `<button data-choice="deny" class="deny">Deny</button></div>`) + `</div>`;
  }
  // messages waiting for the run to end: edit or remove each until it goes; after a run that ended
  // without a reply (cancelled, failed, server restart) they stay, with Send now
  function inboxHtml(inbox, busy) {
    if (!inbox.length) return "";
    return inbox.map((m, i) => `<div class="rv-msg rv-inbox" data-inbox="${attr(m.id)}"><div class="rv-meta">⏳ queued ${i + 1} of ${inbox.length} · ${m.time}` +
      `${busy ? " · goes when this run ends" : ""}</div>${m.selection ? selHtml(m.selection) : ""}${m.shown_notes ? notesHtml(m.shown_notes) : ""}${esc(m.text)}` +
      `<div class="rv-row"><button data-iop="edit">✎ edit</button><button data-iop="remove">✕ remove</button></div></div>`).join("") +
      (busy ? "" : `<div class="rv-row"><button data-iop="send" class="primary">Send now (${inbox.length === 1 ? "1 message" : "as one message"})</button></div>`);
  }
  $("rv-thread").addEventListener("click", e => {
    const ib = e.target.closest("[data-iop]");
    if (ib) {
      const op = ib.dataset.iop, el = ib.closest("[data-inbox]"), id = el && el.dataset.inbox;
      if (op === "send") return post("inbox", {op: "send"});
      if (op === "remove") return post("inbox", {op: "remove", id});
      const m = (state.inbox || []).find(x => x.id === id), text = m && prompt("Edit the queued message:", m.text);
      if (text != null && text.trim()) post("inbox", {op: "edit", id, text});
      return;
    }
    const b = e.target.closest("[data-choice]"), row = b && b.closest("[data-ask]");
    if (!row) return;
    row.querySelectorAll("button").forEach(x => x.disabled = true);
    post("answer", {id: row.dataset.ask, choice: b.dataset.choice});
  });
  const refresh = () => api("state?agent=" + encodeURIComponent(AGENT)).then(render);
  const post = (path, body) => api(path, body).then(r => { if (r.error) alert(r.error); refresh(); });

  $("rv-btn").onclick = () => {
    $("rv-panel").classList.toggle("open");
    if ($("rv-panel").classList.contains("open") && state && scrollToEnd) {   // no state yet: the first render() does it
      $("rv-thread").scrollTop = $("rv-thread").scrollHeight; scrollToEnd = false;   // first open: newest message
    }
    if ($("rv-panel").classList.contains("open") && state && state.status === "unread") post("status", {status: "read"});
  };
  $("rv-x").onclick = () => $("rv-panel").classList.remove("open");
  $("rv-save").onclick = () => {
    if (files.some(f => !f.path)) return alert("Wait until the files are uploaded.");
    // the files go as a line naming them (paths in the agent's folder): the thread, the queue and the
    // prompt all carry it as text, and the agent opens them with Read
    const text = [$("rv-text").value.trim(), files.length ? "Attached files: " + files.map(f => f.path).join(", ") : ""]
      .filter(Boolean).join("\n\n");
    if (!text && !notePins.length) return;   // sticky notes alone: the box may be empty
    $("rv-text").value = "";
    files = []; showFiles();
    scrollToEnd = true;   // show the message just sent
    post("comment", Object.assign({text}, pinned ? {selection: pinned} : {}, notePins.length ? {notes: notePins} : {}));
    pin(null);
    notePins = []; showNotePins();
  };

  // Files dragged onto the page: dropped anywhere, they open the panel and are saved in the agent's
  // pasted/ at once (attach, attachments.py), shown as chips above the box until the message goes.
  // dragover/drop are cancelled on the whole window, so a drop never makes the browser open the file
  // in place of the page (and lose the message being typed).
  const FILES_MAX = 5, FILE_MB = 20;   // attachments.FILE_MAX
  const isFileDrag = e => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  const kb = n => n < 1 << 20 ? Math.max(1, Math.round(n / 1024)) + " KB" : (n / (1 << 20)).toFixed(1) + " MB";
  function showFiles() {
    $("rv-files").style.display = files.length ? "flex" : "none";
    $("rv-files").innerHTML = files.map((f, i) =>
      `<span class="rv-file${f.path ? "" : " up"}" title="${attr(f.path || "uploading…")}"><span>📄 ${esc(f.name)}</span>` +
      `<i>${f.path ? kb(f.size) : "uploading…"}</i><button data-i="${i}" title="Don't send this file">&times;</button></span>`).join("");
  }
  $("rv-files").addEventListener("click", e => {
    const b = e.target.closest("[data-i]");
    if (b) files.splice(+b.dataset.i, 1), showFiles();   // the saved copy stays in pasted/
  });
  // A PNG, JPEG or WebP image is downscaled here to at most MAX_PX on its long side (about what Claude
  // looks at; more only costs tokens), on white (a window screenshot's transparent shadow would turn black
  // as JPEG). It keeps its type, except that a PNG still over 1 MB becomes JPEG when that is smaller.
  // GIF (may be animated), SVG and the rest go as they are.
  const MAX_PX = 1568, SCALABLE = /^image\/(png|jpeg|webp)$/;
  function shrink(file) {
    if (!SCALABLE.test(file.type) || !window.createImageBitmap) return Promise.resolve(file);
    return createImageBitmap(file).then(bmp => {
      const k = MAX_PX / Math.max(bmp.width, bmp.height);
      if (k >= 1) return file;
      const c = document.createElement("canvas"), g = c.getContext("2d");
      c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(bmp, 0, 0, c.width, c.height);
      const blob = (type, q) => new Promise(ok => c.toBlob(ok, type, q));
      return blob(file.type, file.type === "image/png" ? undefined : 0.9)
        .then(b => b && (file.type !== "image/png" || b.size <= 1 << 20) ? b :
          blob("image/jpeg", 0.85).then(j => !b || (j && j.size < b.size) ? j : b))
        .then(b => {
          if (!b) return file;
          const ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}[b.type] || ".png";
          return new File([b], file.name.replace(/\.[^.]*$/, "") + ext, {type: b.type});
        });
    }).catch(() => file);   // not decodable here: the server still gets the original
  }
  function attach(list) {
    const room = FILES_MAX - files.length;
    if (list.length > room) alert("At most " + FILES_MAX + " files per message: " + (list.length - Math.max(room, 0)) + " left out.");
    [...list].slice(0, Math.max(room, 0)).forEach(orig => {
      if (!orig.size && !orig.type) return alert(orig.name + ": a folder can't be attached; drop the files in it.");
      const f = {name: orig.name, size: orig.size, path: null};
      files.push(f);
      const drop = msg => { files = files.filter(x => x !== f); showFiles(); alert(msg); };
      shrink(orig).then(file => {
        if (file.size > FILE_MB << 20) return drop(file.name + " is over " + FILE_MB + " MB.");
        f.name = file.name; f.size = file.size;
        const reader = new FileReader();
        reader.onerror = () => drop(file.name + " couldn't be read.");
        reader.onload = () => api("attach", {name: file.name, data: reader.result.slice(reader.result.indexOf(",") + 1)})
          .then(r => {
            if (r.error) throw new Error(r.error);
            f.path = r.path; showFiles();
          })
          .catch(err => drop(file.name + ": " + err.message));
        reader.readAsDataURL(file);
      });
    });
    showFiles();
  }
  // ⌘V / Ctrl+V of an image (a screenshot, an image copied in a browser or an editor) attaches it.
  // The paste event's clipboardData works over plain http (navigator.clipboard.read() needs https).
  // A clipboard that also holds plain text is left alone: a file copied in Finder or Explorer comes
  // as its name plus its icon, and the name is what should paste.
  $("rv-text").addEventListener("paste", e => {
    const cd = e.clipboardData;
    const got = cd ? [...cd.items].filter(i => i.kind === "file").map(i => i.getAsFile()).filter(Boolean) : [];
    if (!got.length || [...cd.types].includes("text/plain")) return;
    e.preventDefault();
    attach(got.map(x => x.name && x.name !== "image.png" ? x :
      new File([x], "screenshot." + ((x.type.split("/")[1] || "png").replace("jpeg", "jpg")), {type: x.type})));
  });
  // 📎: pick files the same way
  $("rv-attach").onclick = () => $("rv-pick").click();
  $("rv-pick").onchange = () => { attach($("rv-pick").files); $("rv-pick").value = ""; $("rv-text").focus(); };
  let dragDepth = 0;
  window.addEventListener("dragenter", e => {
    if (!isFileDrag(e)) return;
    dragDepth++;
    $("rv-panel").classList.add("open", "rv-dragging");
  });
  window.addEventListener("dragleave", e => {
    if (isFileDrag(e) && --dragDepth <= 0) dragDepth = 0, $("rv-panel").classList.remove("rv-dragging");
  });
  window.addEventListener("dragover", e => { if (isFileDrag(e)) e.preventDefault(), e.dataTransfer.dropEffect = "copy"; });
  window.addEventListener("drop", e => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragDepth = 0;
    $("rv-panel").classList.remove("rv-dragging");
    if (e.dataTransfer.files.length) attach(e.dataTransfer.files), $("rv-text").focus();
  });
  // Enter sends (the Send handler stays the one path); Shift+Enter is a newline, and so is Enter while an
  // IME is composing or while the schedule editor is open. While the agent is busy the message is queued.
  $("rv-text").addEventListener("keydown", e => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    if (!schedEditing() && !$("rv-save").disabled) $("rv-save").click();
  });
  $("rv-model").onchange = () => post("model", {model: $("rv-model").value});
  $("rv-autocompact").onchange = () => {
    const ac = $("rv-autocompact");
    if (ac.value === "now") { ac.value = state.auto_compact; scrollToEnd = true; post("compact", {}); return; }   // an action, not a setting
    post("autocompact", {limit: +ac.value});
  };
  // Schedule…: the editor in the footer, for a new schedule or one from the list (edit). Schedules are held
  // on the server (agents.py), so they go even if this tab is closed. The server checks the fields and
  // says when it would run next (op "preview"), by its own clock and time zone.
  const sched = {id: null, kind: "once", days: [], fromBox: false, sessTouched: false};
  const schedEditing = () => $("rv-sedit").style.display === "block";
  const schedClose = () => { $("rv-sedit").style.display = "none"; };
  const schedFields = () => ({kind: sched.kind, date: $("rv-sdate").value, days: sched.days, time: $("rv-stime").value,
    session: (document.querySelector("input[name=rv-ssess]:checked") || {}).value});
  let previewTimer = null;
  function schedPreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => api("schedule", Object.assign({op: "preview"}, schedFields())).then(r => {
      $("rv-snext").className = r.error ? "err" : "";
      $("rv-snext").textContent = r.error || "Next: " + r.next.join(", ");
    }), 250);
  }
  function schedShow() {
    document.querySelectorAll("#rv-skind button").forEach(b => b.classList.toggle("on", b.dataset.kind === sched.kind));
    document.querySelectorAll("#rv-sdays button").forEach(b => b.classList.toggle("on", sched.days.includes(+b.dataset.day)));
    $("rv-sdaterow").style.display = sched.kind === "once" ? "" : "none";
    $("rv-sdaysrow").style.display = sched.kind === "weekly" ? "" : "none";
    // a once goes into this chat like Send later did; repeating ones start fresh like Repeat did, unless picked
    if (!sched.sessTouched)
      document.querySelector(`input[name=rv-ssess][value=${sched.kind === "once" ? "continue" : "fresh"}]`).checked = true;
    $("rv-stz").textContent = sched.kind === "hourly" ? "every hour at this minute" : "server time (" + (state.tz || "?") + ")";
    schedPreview();
  }
  function schedOpen(s) {   // s: an entry of state.schedules to edit; none: a new one
    const [day, hm] = state.now.split(" ");
    if (s) {
      Object.assign(sched, {id: s.id, kind: s.kind, days: (s.days || []).slice(), fromBox: false, sessTouched: true});
      $("rv-sdate").value = s.date || day;
      $("rv-stime").value = s.time;
      $("rv-stext").value = s.text;
      document.querySelector(`input[name=rv-ssess][value=${s.session}]`).checked = true;
    } else {
      // Once, at the next full hour by the server's clock; the message from the box, else the last one sent
      const next = new Date(day + "T" + hm.slice(0, 2) + ":00:00"), p = n => String(n).padStart(2, "0");
      next.setHours(next.getHours() + 1);
      const box = $("rv-text").value.trim(), last = state.thread.filter(m => m.role === "user").pop();
      Object.assign(sched, {id: null, kind: "once", days: [(next.getDay() + 6) % 7], fromBox: !!box, sessTouched: false});
      $("rv-sdate").value = next.getFullYear() + "-" + p(next.getMonth() + 1) + "-" + p(next.getDate());
      $("rv-stime").value = p(next.getHours()) + ":00";
      $("rv-stext").value = box || (last ? last.text : "");
    }
    $("rv-sedit").style.display = "block";
    schedShow();
    $("rv-stext").focus();
  }
  $("rv-sched").onclick = () => schedEditing() && !sched.id ? schedClose() : schedOpen();
  $("rv-skind").addEventListener("click", e => {
    const b = e.target.closest("[data-kind]");
    if (b) sched.kind = b.dataset.kind, schedShow();
  });
  $("rv-sdays").addEventListener("click", e => {
    const b = e.target.closest("[data-day]");
    if (!b) return;
    const d = +b.dataset.day;
    sched.days = sched.days.includes(d) ? sched.days.filter(x => x !== d) : sched.days.concat(d).sort((x, y) => x - y);
    schedShow();
  });
  ["rv-sdate", "rv-stime"].forEach(id => $(id).addEventListener("input", schedPreview));
  document.querySelectorAll("input[name=rv-ssess]").forEach(r => r.onchange = () => { sched.sessTouched = true; });
  $("rv-ssave").onclick = () => {
    const text = $("rv-stext").value.trim();
    if (!text) return alert("Write the message to send.");
    // text selected in the page goes with a new once only (a repeating one would quote stale lines)
    const body = Object.assign(schedFields(), {text}, sched.id ? {id: sched.id} : {},
      pinned && sched.kind === "once" && !sched.id ? {selection: pinned} : {});
    api("schedule", body).then(r => {
      if (r.error) return alert(r.error);
      if (sched.fromBox && text === $("rv-text").value.trim()) { $("rv-text").value = ""; pin(null); }
      schedClose(); scrollToEnd = true; refresh();
    });
  };
  $("rv-scancel").onclick = schedClose;
  $("rv-slist").addEventListener("click", e => {
    const b = e.target.closest("[data-op]");
    if (!b) return;
    if (b.dataset.op === "edit") return schedOpen(state.schedules.find(s => s.id === b.dataset.sid));
    if (b.dataset.op === "delete" && !confirm("Delete this scheduled message?")) return;
    post("schedule", {op: b.dataset.op, id: b.dataset.sid});
  });
  $("rv-status").onclick = () => {
    if ($("rv-status").classList.contains("tog")) post("status", {status: state.status === "unread" ? "read" : "unread"});
  };
  $("rv-new").onclick = () => { scrollToEnd = true; post("newchat", {}); };
  $("rv-close").onclick = () => post("status", {status: $("rv-close").classList.contains("on") ? "read" : "closed"});
  $("rv-cancel").onclick = () => { if (confirm("Stop this agent?")) { scrollToEnd = true; post("cancel", {}); } };
  const grant = always => post("grant", {rules: state.denials.filter(d => !d.blocked && !d.granted).flatMap(d => d.rules), always});
  // Highlight the blocks that differ from index.html as it was before the agent's latest edit:
  // a leaf block (paragraph, list item, cell, heading, image...) whose content isn't in the old copy.
  const BLOCKS = "p,li,h1,h2,h3,h4,h5,h6,pre,blockquote,figcaption,caption,td,th,dt,dd,summary,img,svg,video,iframe,div";
  const SKIP = "#dirai-status,[id^=rv-],[id^=na-],.rv-removed,.rv-del,.dirai-colls,script,style";   // .dirai-colls: added by the server
  const sig = el => el.tagName + "|" + (/^(IMG|VIDEO|IFRAME)$/.test(el.tagName) ? el.getAttribute("src")
    // a diagram (inlined by the server): all of it, so a redraw with the same labels is marked too
    : el.tagName === "SVG" || el.tagName === "svg" ? [...el.attributes].filter(a => a.name !== "class")
      .map(a => a.name + "=" + a.value).join(" ") + ">" + el.innerHTML
    : textSig(el));
  // A block's text, with math compared by its TeX source. The page has its math typeset by KaTeX (whose
  // text is MathML + TeX + glyphs) while the old copy is never rendered (still $..$), so an unchanged
  // block with math would never match and be marked after every run. Each typeset formula becomes its
  // TeX (KaTeX keeps it in an annotation), the delimiters are dropped on both sides, and in a block with
  // math all whitespace too (the delimiters may sit on their own lines).
  const MATH_DELIM = /\$\$?|\\[()[\]]/g, TEX_ANY = /\$|\\[([]/;
  function textSig(el) {
    let t = el.textContent, math = false;
    if (el.querySelector(".katex")) {
      const c = el.cloneNode(true);
      c.querySelectorAll(".katex-display, .katex").forEach(k => {
        if (!c.contains(k)) return;   // inside a .katex-display already replaced
        const tex = k.querySelector('annotation[encoding="application/x-tex"]');
        k.replaceWith(tex ? tex.textContent : k.textContent);
      });
      t = c.textContent, math = true;
    }
    return math || TEX_ANY.test(t) ? t.replace(MATH_DELIM, "").replace(/\s+/g, "") : t.replace(/\s+/g, " ").trim();
  }
  // the folder's files (files.js) aren't part of index.html: never compared with it
  const leaves = root => [...root.querySelectorAll(BLOCKS)].filter(el =>
    !el.closest(SKIP + ",#dirai-files") && !(el.parentElement && el.parentElement.closest("svg")) &&
    !el.querySelector(BLOCKS) && (el.textContent.trim() || /^(IMG|VIDEO|IFRAME|svg|SVG)$/.test(el.tagName)));
  function highlight() {
    fetch("/_review/prev?agent=" + encodeURIComponent(AGENT)).then(r => r.ok ? r.text() : null).then(old => {
      if (old === null) return drawNotes();
      const before = leaves(new DOMParser().parseFromString(old, "text/html").body);
      const free = {};     // signature -> indexes of old blocks not yet matched to a current one
      before.forEach((el, i) => (free[sig(el)] = free[sig(el)] || []).push(i));
      const twin = new Map();   // old block -> the current block with the same content
      const now = leaves(document.body);
      const changed = now.filter(el => {
        const k = free[sig(el)];
        return k && k.length ? (twin.set(before[k.shift()], el), false) : true;
      });
      // An old block gone from between two kept ones that a changed block there mostly repeats was
      // edited: mark the words in it instead (and it is not shown as removed)
      const pos = new Map(now.map((el, i) => [el, i])), edited = new Set();
      let lo = -1, run = [];
      const pair = hi => {
        run.forEach(o => {
          const c = changed.find(el => !edited.has(el) && pos.get(el) > lo && pos.get(el) < hi && el.tagName === o.tagName && wordMarks(o, el));
          if (c) edited.add(c), twin.set(o, c);
        });
        run = [];
      };
      before.forEach(o => {
        if (!twin.has(o)) return run.push(o);
        pair(pos.get(twin.get(o)));
        lo = pos.get(twin.get(o));
      });
      pair(now.length);
      changed.forEach(el => el.classList.add(edited.has(el) ? "rv-edited" : "rv-changed"));
      const removed = showRemoved(before, twin);
      if (changed.length || removed) $("rv-hl").style.display = "";
      undoButtons();
      drawNotes();   // the sticky notes over the change marks (wordMarks split text nodes)
    }).catch(() => drawNotes());
  }
  // Word diff of an edited block (old copy o, current el): if they share enough words, wrap the added
  // words in el in .rv-ins and put the removed ones, struck through, where they were (.rv-del); true then.
  function wordMarks(o, el) {
    // math (rendered, or TeX not rendered yet, which wrapping would break): the whole block
    const MATH = "mjx-container,.MathJax,.katex,math,svg", TEX = /\\\(|\\\[|\$\$|\\begin\{/;
    // (el itself too: HTML marks put inside an <svg>'s text aren't drawn, so its words would vanish)
    if (el.matches(MATH) || o.matches(MATH) || el.querySelector(MATH) || o.querySelector(MATH) || TEX.test(el.textContent) || TEX.test(o.textContent)) return false;
    const tok = t => t.match(/\s+|\S+/g) || [];
    const a = tok(o.textContent), b = tok(el.textContent), n = a.length, m = b.length;
    if (!n || !m || n * m > 4e6 || n > 60000 || m > 60000) return false;
    const same = (x, y) => x === y || (!x.trim() && !y.trim());
    const L = Array.from({length: n + 1}, () => new Uint16Array(m + 1));   // longest common run of words
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--) L[i][j] = same(a[i], b[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const ins = [], dels = [];   // [start, end) in el's text; {at, text}
    let i = 0, j = 0, off = 0, kept = 0;
    while (i < n || j < m) {
      if (i < n && j < m && same(a[i], b[j])) kept += !!b[j].trim(), off += b[j++].length, i++;
      else if (i < n && (j === m || L[i + 1][j] >= L[i][j + 1])) {   // (removed words before the added ones)
        const last = dels[dels.length - 1];
        if (last && last.at === off) last.text += a[i]; else dels.push({at: off, text: a[i]});
        i++;
      } else {
        const last = ins[ins.length - 1];
        if (last && last[1] === off) last[1] += b[j].length; else ins.push([off, off + b[j].length]);
        off += b[j++].length;
      }
    }
    const text = el.textContent, I = ins.filter(([s, e]) => text.slice(s, e).trim()), D = dels.filter(d => d.text.trim());
    // rewritten rather than edited (half its words new, or changed in many places): the whole block is yellow
    const words = t => t.filter(x => x.trim()).length;
    if (kept < 0.5 * Math.max(words(a), words(b)) || I.length + D.length > 2 + kept / 10) return false;
    const nodes = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) nodes.push(w.currentNode);
    let start = 0;
    nodes.forEach((t, k) => {
      const s = t.data, end = start + s.length, last = k === nodes.length - 1;
      const mine = D.filter(d => d.at >= start && (d.at < end || last && d.at === end));
      const cuts = new Set([0, s.length]);
      I.forEach(r => r.forEach(x => x > start && x < end && cuts.add(x - start)));
      mine.forEach(d => cuts.add(d.at - start));
      if (!mine.length && !I.some(([x, y]) => x < end && y > start)) return start = end;
      const pts = [...cuts].sort((x, y) => x - y), frag = document.createDocumentFragment();
      pts.forEach((p, q) => {
        const at = start + p;
        mine.filter(d => d.at === at).forEach(d => {
          const x = document.createElement("del");
          x.className = "rv-del", x.textContent = d.text.replace(/\s+/g, " ");
          frag.appendChild(x);
        });
        const piece = q + 1 < pts.length ? s.slice(p, pts[q + 1]) : "";
        if (!piece) return;
        if (I.some(([x, y]) => x <= at && at < y)) {
          const x = document.createElement("span");
          x.className = "rv-ins", x.textContent = piece;
          frag.appendChild(x);
        } else frag.appendChild(document.createTextNode(piece));
      });
      t.replaceWith(frag);
      start = end;
    });
    return true;
  }
  // Undo (or Redo) on each block of the latest run's changes, at the upper left of its highlight:
  // the server marked where each block starts (<template data-dirai-block>, page_undo.py)
  let undoPlace = null;
  const undoObs = new ResizeObserver(() => undoPlace && undoPlace());
  function undoButtons() {
    const marks = [...document.body.querySelectorAll("template[data-dirai-block]")];
    const all = [...document.body.querySelectorAll("*")];
    const shown = el => el.getClientRects().length > 0;   // none inside a closed <details>
    const buttons = marks.map((m, n) => {
      const from = all.indexOf(m), to = n + 1 < marks.length ? all.indexOf(marks[n + 1]) : all.length;
      const own = all.slice(from + 1, to);
      // its highlight (or the red box of what it removed, put just before or after the mark); else what follows it
      let prev = m.previousElementSibling;
      while (prev && prev.tagName === "TEMPLATE") prev = prev.previousElementSibling;
      const at = (m.hasAttribute("data-undone") ? null : own.find(el => el.matches(".rv-changed,.rv-edited,.rv-removed") && shown(el))
        || (prev && prev.matches(".rv-removed") ? prev : null))
        || all.slice(from + 1).find(el => shown(el) && !el.closest(SKIP + ",template,.rv-undo,#dirai-files"));
      if (!at) return null;
      const redo = m.hasAttribute("data-undone"), b = document.createElement("button");
      b.className = "rv-undo" + (redo ? " rv-redo" : "");
      b.innerHTML = redo ? "Redo &#8631;" : "&#8630; Undo";
      b.title = redo ? "Bring back this change by the agent's latest run" : "Put this part of index.html back as it was before the agent's latest run";
      b.disabled = !!state && (state.status === "working" || state.status === "queued") && !(state.watching || []).length;
      b.onclick = () => api("undo", {block: +m.dataset.diraiBlock}).then(r => {
        if (r.error) return alert(r.error);
        keepOpen();
        location.reload();
      });
      document.body.appendChild(b);
      if (redo) at.classList.add("rv-undone");   // where the undone block is now
      return [b, at];
    }).filter(Boolean);
    const place = () => buttons.forEach(([b, at]) => {
      const r = at.getBoundingClientRect(), list = at.tagName === "LI" && at.parentElement;   // left of its number
      const left = list ? Math.min(r.left, list.getBoundingClientRect().left) : r.left;
      b.style.top = Math.max(0, r.top + scrollY - 2) + "px";   // in the margin, just left of its top line
      b.style.left = Math.max(0, left + scrollX - b.offsetWidth - 6) + "px";
    });
    place();
    undoPlace = buttons.length ? place : null;   // one observer and listener, also after updatePage()
    if (buttons.length && !undoButtons.on) undoButtons.on = true, undoObs.observe(document.body), addEventListener("resize", () => undoPlace && undoPlace());
  }
  // Old blocks with no current twin were removed: show each run of them, collapsed, after the
  // current twin of the old block just before it (or before the first kept block, if none is before).
  function showRemoved(before, twin) {
    let runs = 0, run = [], after = null;
    const placed = new Map();   // spot -> the last box put after it
    const flush = next => {
      if (!run.length) return;
      const box = document.createElement("details");
      box.className = "rv-removed";
      box.innerHTML = `<summary>Removed (${run.length} block${run.length === 1 ? "" : "s"})</summary><div></div>`;
      run.forEach(el => {
        // a cell, list item... out of its table or list: keep only what's inside it
        const part = /^(TD|TH|LI|DT|DD|CAPTION|FIGCAPTION|SUMMARY)$/.test(el.tagName) ? document.createElement("div") : document.importNode(el, false);
        el.childNodes.forEach(n => part.appendChild(document.importNode(n, true)));
        part.querySelectorAll("script").forEach(x => x.remove());
        [part, ...part.querySelectorAll("[id]")].forEach(x => x.removeAttribute("id"));   // the page's ids stay unique
        box.lastChild.appendChild(part);
      });
      // never inside a table, or a <details> that may be closed; runs after the same spot keep their order
      const spot = el => el.closest("table") || el.closest("details") || el;
      if (after) { const at = spot(after); (placed.get(at) || at).after(box); placed.set(at, box); }
      else if (next) spot(next).before(box);
      else document.body.prepend(box);
      runs++, run = [];
    };
    before.forEach(el => {
      if (twin.has(el)) { flush(twin.get(el)); after = twin.get(el); }
      else run.push(el);
    });
    flush(null);
    return runs;
  }
  $("rv-hl").onclick = () => {
    $("rv-hl").textContent = document.body.classList.toggle("rv-nohl") ? "Show changes" : "Hide changes";
  };

  // Links in the agent's replies: [text](#id) scrolls the page to that part of index.html (opening any
  // closed <details> around it) and flashes it. #changes steps through the latest run's changed parts;
  // #file:<name>:<line> goes to a line of a file shown at the end (files.js). Headings without an id
  // get one from their text, by the rule the agents' instructions give (agent_prompts.py).
  const slug = t => t.toLowerCase().replace(/^\s*[\d.]+\s+/, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const headingIds = () => document.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach(h => {
    const id = slug(h.textContent);
    if (h.id || !id || h.closest(SKIP + ",#dirai-files")) return;
    let n = 1;
    while (document.getElementById(n > 1 ? id + "-" + n : id)) n++;
    h.id = n > 1 ? id + "-" + n : id;
  });
  headingIds();
  const JUMP = /\[([^\]\n]+)\]\(#([^()\s"'<>]+)\)/g;   // on escaped text: the label is escaped already
  const jumpLinks = text => esc(text).replace(JUMP, (all, label, id) => `<a class="rv-jump" href="#${id}" data-jump="${id}">${label}</a>`);
  const GONE = "Not on this page: renamed or removed since, or added after this tab loaded (reload it)";
  let changeAt = -1;
  function jumpTarget(id) {
    if (id === "changes") {
      const marks = ".rv-changed,.rv-edited,.rv-removed";
      const all = [...document.querySelectorAll(marks)].filter(el => !el.parentElement.closest(marks));
      return all.length ? all[changeAt = (changeAt + 1) % all.length] : null;
    }
    const f = id.match(/^file:(.+?)(?::(\d+))?$/);
    if (f) {
      const box = [...document.querySelectorAll("#dirai-files details[data-file]")].find(d => d.dataset.file === f[1]);
      if (!box || !f[2]) return box || null;
      const n = +f[2];
      return [...box.querySelectorAll("[data-line]")].find(el => +el.dataset.line <= n && n <= +(el.dataset.lineEnd || el.dataset.line)) || box;
    }
    const el = document.getElementById(id);
    return el && !el.closest(SKIP + ",#rv-btn,#rv-ask") ? el : null;
  }
  // ids that aren't on the page show as dotted text, not dead links (#changes and files load later)
  function markBroken(box) {
    box.querySelectorAll(".rv-jump").forEach(a => {
      if (a.dataset.jump !== "changes" && !a.dataset.jump.startsWith("file:") && !jumpTarget(a.dataset.jump))
        a.classList.add("rv-broken"), a.title = GONE;
    });
  }
  // A reply longer than about 8 lines (60 characters each) shows its start, faded, with a "more" toggle:
  // the details belong in index.html (agent_prompts.py asks for 3 lines). Expanded replies stay expanded.
  const LONG = 8, expanded = new Set();
  const rows = t => t.split("\n").reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 60)), 0);
  function replyHtml(m) {
    const body = jumpLinks(m.text);
    if (rows(m.text) <= LONG) return body;
    const open = expanded.has(m.time);
    return `<div class="rv-body${open ? "" : " rv-clip"}">${body}</div><button class="rv-more" data-more="${attr(m.time)}">${open ? "less" : "more"}</button>`;
  }
  $("rv-thread").addEventListener("click", e => {
    const b = e.target.closest(".rv-more");
    if (!b) return;
    const open = b.previousElementSibling.classList.toggle("rv-clip") === false;
    if (open) expanded.add(b.dataset.more); else expanded.delete(b.dataset.more);
    b.textContent = open ? "less" : "more";
  });
  $("rv-thread").addEventListener("click", e => {
    const a = e.target.closest(".rv-jump");
    if (!a) return;
    e.preventDefault();
    const el = jumpTarget(a.dataset.jump);
    if (!el) return a.classList.add("rv-broken"), a.title = a.dataset.jump === "changes" ? "No changes are highlighted on this page" : GONE;
    if (a.dataset.jump === "changes" && document.body.classList.contains("rv-nohl")) $("rv-hl").click();
    go(el);
  });
  function go(el) {   // open the <details> around el, scroll to it and flash it
    if (el.tagName === "DETAILS") el.open = true;
    for (let d = el.parentElement && el.parentElement.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
    el.scrollIntoView({behavior: "smooth", block: "center"});
    el.classList.remove("rv-flash"), void el.offsetWidth, el.classList.add("rv-flash");   // restart the flash
    setTimeout(() => el.classList.remove("rv-flash"), 1900);
  }
  highlight();

  // The page updates itself: when a run ends (dirai:run-done) and index.html changed, its new content
  // replaces the old in place. The panel, what is typed in it, the scroll position and which <details>
  // are open stay; the highlights, Undo buttons and heading ids are redone. A page with scripts of its
  // own (plotly, MathJax...) can't be swapped like that: it reloads, the panel kept open (or, with a
  // message being typed, the toast offers the reload).
  const ME = document.currentScript.src.replace(/[^/?#]*([?#].*)?$/, "");   // DirAI's scripts are served from here
  const KEEP = "script,style,#rv-btn,#rv-ask,#rv-addnote,#rv-notepop,#rv-panel,#rv-toast,#dirai-files,[id^=na-],.rv-undo";
  const ownScript = s => s.type === "application/json" ||
    !!s.getAttribute("src") && new URL(s.getAttribute("src"), location.href).href.startsWith(ME);
  const pageNodes = body => [...body.childNodes].filter(n => !(n.nodeType === 1 && n.matches(KEEP)) && (n.nodeType === 1 || n.textContent.trim()));
  // what a change is measured on: the page's own nodes, without the server's status bar and colleagues list
  const pageKey = doc => pageNodes(doc.body).map(n => n.nodeType !== 1 ? n.textContent.trim() :
    n.matches("#dirai-status,.dirai-colls") ? "" : n.outerHTML).join("\n");
  const fetchPage = () => fetch(location.href, {cache: "no-store"}).then(r => r.ok ? r.text() : null)
    .then(t => t && new DOMParser().parseFromString(t, "text/html")).catch(() => null);
  let pageSeen = null, updateTimer = null, toastTimer = null;   // pageSeen: pageKey of the page this tab shows
  fetchPage().then(d => { if (d && pageSeen === null) pageSeen = pageKey(d); });
  function toast(msg, label, action) {
    $("rv-toastmsg").textContent = msg;
    $("rv-toastgo").textContent = label;
    $("rv-toastgo").onclick = () => { $("rv-toast").style.display = "none"; action(); };
    $("rv-toast").style.display = "flex";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("rv-toast").style.display = "none", 15000);
  }
  $("rv-toastx").onclick = () => $("rv-toast").style.display = "none";
  const keepOpenReload = () => {
    keepOpen();
    location.reload();
  };
  function busyInPage() {   // the owner is selecting text in the page, or typing in a field of it
    const s = window.getSelection(), a = document.activeElement, inPanel = n => n && (n.nodeType === 1 ? n : n.parentElement).closest("#rv-panel");
    return s && !s.isCollapsed && !inPanel(s.anchorNode) || a && a.matches("input,textarea,select,[contenteditable]") && !inPanel(a);
  }
  function updatePage() {
    clearTimeout(updateTimer);
    if (busyInPage()) return updateTimer = setTimeout(updatePage, 3000);   // after they stop
    fetchPage().then(doc => {
      if (!doc) return;
      const key = pageKey(doc);
      if (key === pageSeen) return;   // index.html didn't change: nothing happens
      if (busyInPage()) return updateTimer = setTimeout(updatePage, 3000);
      const own = [...doc.querySelectorAll("script")].every(ownScript) && [...document.querySelectorAll("script")].every(ownScript);
      if (!own) return $("rv-text").value.trim() ? toast("Page updated", "Reload", keepOpenReload) : keepOpenReload();
      try { swap(doc); } catch (e) { return keepOpenReload(); }
      pageSeen = key;
      toast("Page updated", "Show changes", () => {
        if (document.body.classList.contains("rv-nohl")) $("rv-hl").click();
        changeAt = -1;
        const el = jumpTarget("changes");
        if (el) go(el);
      });
    });
  }
  function swap(doc) {
    const dkey = d => d.id || ((d.querySelector(":scope > summary") || d).textContent.replace(/\s+/g, " ").trim().slice(0, 120));
    const pageDetails = () => [...document.querySelectorAll("details")].filter(d => !d.closest(SKIP + ",#dirai-files"));
    const wasOpen = new Map(pageDetails().map(d => [dkey(d), d.open]));
    const x = scrollX, y = scrollY;
    const old = pageNodes(document.body), frag = document.createDocumentFragment();
    pageNodes(doc.body).forEach(n => frag.appendChild(document.importNode(n, true)));
    if (old.length) old[0].before(frag); else document.body.prepend(frag);
    old.forEach(n => n.remove());
    document.querySelectorAll(".rv-undo").forEach(b => b.remove());
    undoPlace = null;
    if (doc.title) document.title = doc.title;
    pageDetails().forEach(d => { const k = dkey(d); if (wasOpen.has(k)) d.open = wasOpen.get(k); });
    headingIds();
    $("rv-hl").style.display = "none";
    changeAt = -1;
    highlight();
    if (state) render.shownPerms = null, render(state);   // the permissions list at the end of the card
    $("rv-thread").querySelectorAll(".rv-jump.rv-broken").forEach(a => { a.classList.remove("rv-broken"); a.title = ""; });
    markBroken($("rv-thread"));
    scrollTo(x, y);
  }
  document.addEventListener("dirai:run-done", () => updatePage());

  // Text the owner selects in index.html goes with their next message (quoted, with the nearest heading;
  // the server adds the source lines). Selecting while the panel is open attaches it right away;
  // otherwise the "Ask AI about this" button next to the selection does. Text only.
  const SEL_MAX = 4000;
  let pinned = null;
  const lineCount = t => t.split("\n").filter(l => l.trim()).length;
  function selHtml(sel) {
    const where = (sel.file ? ` · ${esc(sel.file)}` : "") + (sel.heading ? ` · near "${esc(sel.heading)}"` : "") +
      (sel.lines ? ` · line${sel.lines[0] === sel.lines[1] ? " " + sel.lines[0] : "s " + sel.lines[0] + "–" + sel.lines[1]}` : "");
    return `<details class="rv-sel"><summary>📎 Selected text (${lineCount(sel.text)} line${lineCount(sel.text) === 1 ? "" : "s"})${where}</summary>` +
      `<div class="rv-quote">${esc(sel.text)}</div></details>`;
  }
  function pin(sel) {
    pinned = sel;
    const chip = $("rv-chip");
    chip.style.display = sel ? "flex" : "none";
    if (!sel) return chip.innerHTML = "";
    chip.innerHTML = `<details><summary>📎 "${esc(sel.text.replace(/\s+/g, " ").slice(0, 70))}${sel.text.length > 70 ? "…" : ""}" ` +
      `(${sel.file ? esc(sel.file) + ", " : ""}${lineCount(sel.text)} line${lineCount(sel.text) === 1 ? "" : "s"}${sel.cut ? ", cut to " + SEL_MAX + " characters" : ""})</summary>` +
      `<div class="rv-quote">${esc(sel.text)}</div></details><button id="rv-unsel" title="Don't send the selection">&times;</button>`;
    $("rv-unsel").onclick = () => pin(null);
  }
  // {text, heading} of a selection in index.html, or {text, file, lines, rendered} of one in a file of
  // the folder shown at its end (files.js: every line, or rendered .md block, carries its numbers); else null
  function indexSelection() {
    const s = window.getSelection();
    if (!s || s.isCollapsed || !s.rangeCount) return null;
    const r = s.getRangeAt(0), node = n => n.nodeType === 1 ? n : n.parentElement;
    if ([r.startContainer, r.endContainer].some(n => !node(n) || node(n).closest(SKIP + ",#rv-btn,#rv-ask"))) return null;
    let text = s.toString().replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!text) return null;
    const cut = text.length > SEL_MAX;
    if (cut) text = text.slice(0, SEL_MAX);
    let heading = "";
    document.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach(h => {
      if (!h.closest(SKIP) && h.compareDocumentPosition(r.startContainer) & Node.DOCUMENT_POSITION_FOLLOWING)
        heading = h.textContent.replace(/\s+/g, " ").trim().slice(0, 200);
    });
    const line = n => node(n).closest("#dirai-files [data-line]");
    const first = line(r.startContainer);
    let last = line(r.endContainer);
    // a selection that ends at the very start of a line (triple click, dragging to the line's edge) ends on the one before
    if (last && last !== first && r.endOffset === 0) {   // (skipping a box of removed lines)
      let prev = last.previousElementSibling;
      while (prev && !prev.dataset.line) prev = prev.previousElementSibling;
      if (prev) last = prev;
    }
    const file = el => el && el.closest("details[data-file]").dataset.file;
    if (first || last) {
      if (!first || !last || file(first) !== file(last)) return null;   // half in a file, or across two
      // a rendered .md block spans lines (data-line-end); the server narrows them to the selected text
      return {text, heading: "", file: file(first), lines: [+first.dataset.line, +(last.dataset.lineEnd || last.dataset.line)],
              rendered: !!first.dataset.rendered, cut, rect: r.getBoundingClientRect()};
    }
    // in a diagram the server put inline (svg_inline.py): the file it came from, whose lines the agent gets
    const fig = node(r.startContainer).closest("svg[data-dirai-src]");
    if (fig) return {text, heading, file: fig.getAttribute("data-dirai-src"), svg: true, cut, rect: r.getBoundingClientRect()};
    return {text, heading, cut, rect: r.getBoundingClientRect()};
  }
  function onSelect() {
    const sel = indexSelection(), ask = $("rv-ask"), add = $("rv-addnote");
    if (!sel) return ask.style.display = add.style.display = "none";
    const x = Math.min(sel.rect.right + scrollX, scrollX + innerWidth - 300), y = sel.rect.bottom + scrollY + 6 + "px";
    add.sel = Object.assign(sel, noteContext());   // + Sticky note: also with the panel open
    add.style.top = y;
    add.style.display = "block";
    if ($("rv-panel").classList.contains("open")) {
      ask.style.display = "none";
      add.style.left = x + "px";
      return pin(sel);
    }
    ask.style.left = x + "px";
    ask.style.top = y;
    ask.style.display = "block";
    ask.sel = sel;
    add.style.left = x + ask.offsetWidth + 6 + "px";
  }
  document.addEventListener("mouseup", () => setTimeout(onSelect));   // after the click clears or sets it
  document.addEventListener("keyup", e => { if (e.shiftKey) onSelect(); });
  $("rv-ask").onmousedown = e => e.preventDefault();   // keep the selection in index.html
  $("rv-ask").onclick = () => {
    pin($("rv-ask").sel); $("rv-ask").style.display = $("rv-addnote").style.display = "none";
    if (!$("rv-panel").classList.contains("open")) $("rv-btn").click();
    $("rv-text").focus();
  };

  // Sticky notes (notes.py, kept in the agent's .notes.json): + Sticky note on a selection adds one;
  // each is drawn as a yellow mark with its number, its text in a pop-up on hover (or tap); the panel's
  // Sticky notes list has them all, and Send notes puts the open ones in the next message as chips
  // (× on a chip leaves that note out; the box may stay empty). After the run the server marks each
  // from the agent's "<n>: done|open" lines: blue = sent, grey ✓ = done (gone after the next run).
  let noteList = [], notesShown = null, moved = new Set();
  const NOTE_CTX = 32;   // characters (whitespace removed) of page text kept before and after a note's text
  const squash = s => s.replace(/\s+/g, "");
  // compared without case: a selection holds text as shown, which CSS may have capitalised (text-transform)
  const lower1 = c => { const l = c.toLowerCase(); return l.length === c.length ? l : c; };
  const lowered = s => Array.from(s, lower1).join("");
  // the page's text nodes a note can sit in (not the panel, the Files section, diagrams or math)
  const NOTE_SKIP = SKIP + ",#dirai-files,svg,.katex,mjx-container,textarea,select,button";
  function pageText() {
    const nodes = [], offs = [];
    let str = "";
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {acceptNode: n =>
      n.parentElement && !n.parentElement.closest(NOTE_SKIP) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
    while (w.nextNode()) {
      const t = w.currentNode, d = t.data;
      for (let i = 0; i < d.length; i++) if (!/\s/.test(d[i])) str += lower1(d[i]), nodes.push(t), offs.push(i);
    }
    return {str, nodes, offs};
  }
  // the page text just before and after the current selection, to tell copies of the same phrase apart
  function noteContext() {
    const s = window.getSelection();
    if (!s || !s.rangeCount) return {};
    const r = s.getRangeAt(0), a = document.createRange(), b = document.createRange();
    try {
      a.setStart(document.body, 0), a.setEnd(r.startContainer, r.startOffset);
      b.setStart(r.endContainer, r.endOffset), b.setEnd(document.body, document.body.childNodes.length);
    } catch (e) { return {}; }
    return {before: squash(a.toString()).slice(-NOTE_CTX), after: squash(b.toString()).slice(0, NOTE_CTX)};
  }
  // [start, end) of note n in the page text: the copy whose neighbours match best; null if gone.
  // A selection's text can lack page text in between (a code table's line numbers with user-select:none,
  // hidden rows): then its first and last NOTE_KEY characters are matched, the end near the start.
  const NOTE_KEY = 24;
  function findNote(pt, n) {
    const key = lowered(squash(n.text));
    if (!key) return null;
    const bf = lowered(squash(n.before || "")), af = lowered(squash(n.after || ""));
    let best = null, score = -1;
    const rate = (i, j) => {   // how well the page around [i, j) matches the note's neighbours
      let s = 0, t = 0;
      while (s < bf.length && pt.str[i - 1 - s] === bf[bf.length - 1 - s]) s++;
      while (t < af.length && pt.str[j + t] === af[t]) t++;
      if (s + t > score) score = s + t, best = [i, j];
    };
    for (let i = pt.str.indexOf(key); i >= 0; i = pt.str.indexOf(key, i + 1)) rate(i, i + key.length);
    if (best || key.length < 2 * NOTE_KEY) return best;
    const head = key.slice(0, NOTE_KEY), tail = key.slice(-NOTE_KEY), span = 2 * key.length + 200;
    for (let i = pt.str.indexOf(head); i >= 0; i = pt.str.indexOf(head, i + 1)) {
      const j = pt.str.indexOf(tail, i + head.length);
      if (j >= 0 && j + tail.length - i <= span) rate(i, j + tail.length);
    }
    return best;
  }
  function wrapNote(pt, [a, b], n) {
    const parts = new Map();   // text node -> [first, last] offsets of the note in it
    for (let k = a; k < b; k++) {
      const p = parts.get(pt.nodes[k]);
      if (p) p[1] = pt.offs[k]; else parts.set(pt.nodes[k], [pt.offs[k], pt.offs[k]]);
    }
    const marks = [];
    parts.forEach(([x, y], t) => {
      const mid = x > 0 ? t.splitText(x) : t;
      if (y - x + 1 < mid.data.length) mid.splitText(y - x + 1);
      const m = document.createElement("mark");
      m.className = "rv-note " + n.state + (n.noanswer ? " noanswer" : ""), m.dataset.note = n.id;
      mid.replaceWith(m), m.appendChild(mid);
      marks.push(m);
    });
    const last = marks[marks.length - 1];
    if (last) last.classList.add("rv-nend"), last.dataset.n = n.n;
  }
  // A note whose text is gone (the agent rewrote it) gets a pin, a numbered mark holding no text, at the
  // first of: where the text was (between the words that were around it, or next to one side of them
  // when that side is there once), where the agent said it changed it (--at), its heading. null: list only.
  const NOTE_SIDE = 8;   // characters of a neighbour, at least, to look for
  function notePlace(pt, n) {
    const bf = lowered(squash(n.before || "")), af = lowered(squash(n.after || ""));
    const all = s => { const out = []; if (s.length >= NOTE_SIDE) for (let i = pt.str.indexOf(s); i >= 0; i = pt.str.indexOf(s, i + 1)) out.push(i); return out; };
    const B = all(bf).map(i => i + bf.length), A = all(af);
    let k = B.find(b => A.some(a => a >= b && a - b < 4000));
    if (k === undefined) k = B.length === 1 ? B[0] : A.length === 1 ? A[0] : undefined;
    if (k !== undefined && k < pt.str.length) return {node: pt.nodes[k], off: pt.offs[k], where: "where its text was"};
    const ans = (n.thread || []).filter(e => e.at).pop(), at = n.at || ans && ans.at;
    const el = at && !/^#?file:/.test(at) && jumpTarget(at.replace(/^#/, ""));
    if (el && !el.closest(SKIP)) return {el, where: "where the agent changed it"};
    const h = n.heading && [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find(x => !x.closest(SKIP) && x.textContent.trim() === n.heading.trim());
    return h ? {el: h, end: true, where: "under its heading"} : null;
  }
  function pinNote(place, n) {
    const m = document.createElement("mark");
    m.className = "rv-note rv-nend rv-moved " + n.state + (n.noanswer ? " noanswer" : "");
    m.dataset.note = n.id, m.dataset.n = n.n, m.dataset.where = place.where;
    if (place.node) {
      const rest = place.off > 0 ? place.node.splitText(place.off) : place.node;
      rest.parentNode.insertBefore(m, rest);
    } else if (place.end) place.el.append(m);
    else if (place.el.matches("table,thead,tbody,tr,ul,ol,dl,pre,svg")) place.el.before(m);
    else place.el.prepend(m);
  }
  function undrawNotes() {
    const parents = new Set();
    document.querySelectorAll("mark.rv-note").forEach(m => { parents.add(m.parentNode); m.replaceWith(...m.childNodes); });
    parents.forEach(p => p.isConnected && p.normalize());
    document.querySelectorAll(".rv-svgpin").forEach(g => g.remove());
    document.querySelectorAll("tspan.rv-svgnote").forEach(t => { parents.add(t.parentNode); t.replaceWith(...t.childNodes); });
    parents.forEach(p => p.isConnected && p.normalize());
  }
  // A note on a diagram the server put inline (svg_inline.py): no <mark> in SVG, so its words go in a
  // <tspan> with a highlight (a stroke under the letters), and a numbered badge goes after their <text>.
  // The diagram's text stays the same. False if the text isn't there.
  function drawSvgNote(n) {
    const fig = [...document.querySelectorAll("svg[data-dirai-src]")].find(s => s.getAttribute("data-dirai-src") === n.file);
    if (!fig) return false;
    const nodes = [], offs = [];
    let str = "";
    const w = document.createTreeWalker(fig, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      const t = w.currentNode;
      for (let i = 0; i < t.data.length; i++) if (!/\s/.test(t.data[i])) str += lower1(t.data[i]), nodes.push(t), offs.push(i);
    }
    const at = findNote({str, nodes, offs}, n);
    if (!at) return false;
    // the note's part of each text node in a <tspan> (no x/y: the text is laid out as before)
    const parts = new Map(), els = [];
    for (let k = at[0]; k < at[1]; k++) {
      const p = parts.get(nodes[k]);
      if (p) p[1] = offs[k]; else parts.set(nodes[k], [offs[k], offs[k]]);
    }
    parts.forEach(([x, y], t) => {
      const mid = x > 0 ? t.splitText(x) : t;
      if (y - x + 1 < mid.data.length) mid.splitText(y - x + 1);
      const el = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
      el.setAttribute("class", "rv-svgnote " + n.state + (n.noanswer ? " noanswer" : ""));
      el.dataset.note = n.id;
      mid.replaceWith(el), el.appendChild(mid);
      els.push(el);
    });
    const last = els[els.length - 1];
    try {
      const b = (last.closest("text") || last).getBBox(), NS = "http://www.w3.org/2000/svg", g = document.createElementNS(NS, "g");
      g.setAttribute("class", "rv-svgpin " + n.state + (n.noanswer ? " noanswer" : ""));
      g.dataset.note = n.id;
      const label = (n.state === "done" ? "✓" : "") + n.n, wd = 7 * label.length + 6;
      g.innerHTML = `<rect x="${b.x + b.width + 2}" y="${b.y + b.height / 2 - 7}" width="${wd}" height="14" rx="7"/>` +
        `<text x="${b.x + b.width + 2 + wd / 2}" y="${b.y + b.height / 2 + 4}" text-anchor="middle">${esc(label)}</text>`;
      (last.closest("text") || last).after(g);
    } catch (e) { /* not rendered (display:none): the highlight alone */ }
    return true;
  }
  // the mark of a note on the page or in a diagram (the first one)
  const noteMark = id => document.querySelector(`mark.rv-note[data-note="${CSS.escape(id)}"],.rv-svgnote[data-note="${CSS.escape(id)}"]`);
  // marks in the page for the notes on index.html text and on inline diagrams (notes in a file are listed only)
  function drawNotes() {
    undrawNotes();
    moved = new Set();
    const onPage = noteList.filter(n => !n.file);
    if (onPage.length) {
      // found on one reading of the page text, then wrapped from the last on the page to the first, so
      // splitting a text node leaves the offsets before it right; a note overlapping one already wrapped
      // is searched again on the page as it now is
      let pt = pageText();
      const found = [];
      onPage.forEach(n => { const at = findNote(pt, n); if (at) found.push([at, n]); else moved.add(n.id); });
      found.sort((x, y) => y[0][0] - x[0][0]);
      let low = Infinity;
      found.forEach(([at, n]) => {
        if (at[1] > low) pt = pageText(), at = findNote(pt, n);
        if (!at) return moved.add(n.id);
        wrapNote(pt, at, n);
        low = Math.min(low, at[0]);
      });
      // the moved ones: a pin each, the page text read again after each (a pin splits a text node)
      noteList.filter(n => moved.has(n.id)).forEach(n => { const p = notePlace(pageText(), n); if (p) pinNote(p, n); });
    }
    noteList.filter(n => n.svg && n.file).forEach(n => drawSvgNote(n) || moved.add(n.id));
    drawNoteList();
    if (noteObs) noteObs.takeRecords();   // the marks just drawn (and the change highlights before them) aren't page changes
    pageLen = document.body.textContent.length;
  }
  // A page can build or rebuild its content with its own script after panel.js drew the notes (a diff
  // viewer that fetches its data, a section unfolded): when the page's nodes change, a note not drawn
  // yet, or whose mark went with the old nodes, is drawn again.
  let pageLen = 0, noteTimer = null;
  const noteObs = window.MutationObserver ? new MutationObserver(recs => {
    if (!noteList.some(n => !n.file)) return;
    if (!recs.some(r => { const el = r.target.nodeType === 1 ? r.target : r.target.parentElement; return el && !el.closest(SKIP + ",#rv-notepop"); })) return;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => {
      const lost = noteList.some(n => !n.file && !moved.has(n.id) && !document.querySelector(`mark.rv-note[data-note="${CSS.escape(n.id)}"]`));
      if (lost || moved.size && document.body.textContent.length !== pageLen) drawNotes();
    }, 300);
  }) : null;
  if (noteObs) noteObs.observe(document.body, {childList: true, subtree: true, characterData: true});
  const noteQuote = (n, k) => n.text.replace(/\s+/g, " ").slice(0, k) + (n.text.length > k ? "…" : "");
  const NSTATE = {open: "open", sent: "sent, waiting for the agent", done: "done"};
  function drawNoteList() {
    const open = noteList.filter(n => n.state === "open");
    $("rv-notessum").textContent = "Sticky notes" + (noteList.length ? ` (${noteList.length}${open.length && open.length !== noteList.length ? ", " + open.length + " open" : ""})` : "");
    $("rv-notesend").textContent = `Send ${open.length || ""} note${open.length === 1 ? "" : "s"}`.replace("  ", " ");
    $("rv-notesend").disabled = !open.length;
    $("rv-noteclear").style.display = noteList.some(n => n.state === "done") ? "" : "none";
    // the open and sent ones first (the list shows 4 rows, then scrolls), the done ones after, each by number
    $("rv-notelist").innerHTML = noteList.length ? noteList.slice().sort((x, y) => (x.state === "done") - (y.state === "done") || x.n - y.n).map(n =>
      `<div class="rv-nitem ${n.state}" data-nid="${attr(n.id)}"><b>${n.n}</b>` +
      `<span data-nop="go" title="${attr(n.text + (n.note ? "\n\n" + n.note : ""))}">${n.note ? esc(n.note.replace(/\s+/g, " ")) + " · " : ""}<i>“${esc(noteQuote(n, 60))}”</i></span>` +
      `<i>${n.file ? esc(n.file) + (n.lines ? ":" + n.lines[0] : "") + " · " : moved.has(n.id) ? "moved · " : ""}${n.noanswer ? "no answer" : n.state}</i>` +
      `<button data-nop="edit">edit</button><button data-nop="state">${n.state === "done" ? "reopen" : "done"}</button>` +
      `<button data-nop="delete" title="Delete">&times;</button></div>`).join("")
      : '<div class="rv-meta">None yet: select text on the page, then + Sticky note.</div>';
  }
  function renderNotes(list) {
    const key = JSON.stringify(list);
    if (key === notesShown) return;
    notesShown = key, noteList = list;
    notePins = notePins.filter(id => list.some(n => n.id === id && n.state !== "done"));
    showNotePins();
    drawNotes();
  }
  const noteApi = body => api("notes", body).then(r => {
    if (r.error) alert(r.error);
    if (r.notes) renderNotes(r.notes);
  });
  $("rv-addnote").onmousedown = e => e.preventDefault();   // keep the selection
  $("rv-addnote").onclick = () => {
    const sel = $("rv-addnote").sel;
    $("rv-addnote").style.display = $("rv-ask").style.display = "none";
    if (!sel) return;
    if (pinned === sel) pin(null);   // the panel was open: it is a note, not a selection for this message
    noteEditor(`New sticky note on “${noteQuote(sel, 60)}”`, "", {left: sel.rect.left + scrollX, top: sel.rect.bottom + scrollY + 6}, note => {
      window.getSelection().removeAllRanges();
      noteApi({op: "add", note: {text: sel.text, heading: sel.heading, file: sel.file, lines: sel.lines, svg: sel.svg,
        rendered: sel.rendered, before: sel.before, after: sel.after, note}});
    });
  };
  // The note typed in a box in the note's pop-up, where the text is (no browser dialog): Save or
  // Ctrl/⌘+Enter keeps it, Cancel or Esc drops it; an empty note is fine (the agent looks at the text).
  // While it is open, hovering other marks leaves it alone.
  let editing = false;
  function noteEditor(title, value, at, save) {
    const pop = $("rv-notepop");
    clearTimeout(popTimer);
    editing = true;
    pop.innerHTML = `<div class="rv-meta">${esc(title)}</div><textarea id="rv-notetext" placeholder="Your note (may stay empty: then the agent just looks at this text)"></textarea>` +
      `<div class="rv-row"><button data-ned="save">Save</button> <button data-ned="cancel">Cancel</button> <span class="rv-meta">Ctrl+Enter saves, Esc cancels</span></div>`;
    pop.style.left = Math.max(scrollX + 4, Math.min(at.left, scrollX + innerWidth - 330)) + "px";
    pop.style.top = at.top + "px";
    pop.style.display = "block";
    const ta = $("rv-notetext"), done = keep => {
      editing = false;
      const t = ta.value;
      hidePop();
      if (keep) save(t.trim());
    };
    ta.value = value;
    ta.focus();
    ta.onkeydown = e => {
      e.stopPropagation();   // the page's own key shortcuts (n / p in a diff viewer) don't fire while typing
      if (e.key === "Escape") done(false);
      else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) e.preventDefault(), done(true);
    };
    pop.querySelector('[data-ned="save"]').onclick = () => done(true);
    pop.querySelector('[data-ned="cancel"]').onclick = () => done(false);
  }
  function noteOp(id, op) {
    const n = noteList.find(x => x.id === id);
    if (!n) return;
    hidePop();
    if (op === "go") {
      const el = noteMark(id) || (n.svg ? [...document.querySelectorAll("svg[data-dirai-src]")].find(s => s.getAttribute("data-dirai-src") === n.file)
        : n.file && jumpTarget("file:" + n.file + (n.lines ? ":" + n.lines[0] : "")));
      return el && go(el);
    }
    if (op === "delete") return noteApi({op: "delete", id});
    if (op === "state") return noteApi({op: "state", id, state: n.state === "done" ? "open" : "done"});
    // the box at the note's mark, or (a note in a file, or moved) near the top of the window
    const m = noteMark(id), r = m && m.getBoundingClientRect();
    const at = r && r.bottom > 0 && r.top < innerHeight ? {left: r.left + scrollX, top: r.bottom + scrollY + 4}
      : {left: scrollX + Math.max(8, innerWidth / 2 - 160), top: scrollY + 80};
    if (op === "edit") noteEditor(`Note ${n.n} on “${noteQuote(n, 60)}”`, n.note || "", at, t => noteApi({op: "edit", id, note: t}));
    // a reply to the agent on the note (E4): saved there, the note open again for the next Send (E5a)
    if (op === "reply") noteEditor(`Reply on note ${n.n} (goes with your next Send)`, "", at, t => t && noteApi({op: "reply", id, text: t}));
  }
  $("rv-notelist").addEventListener("click", e => {
    const b = e.target.closest("[data-nop]"), row = b && b.closest("[data-nid]");
    if (row) noteOp(row.dataset.nid, b.dataset.nop);
  });
  // the pop-up of a note: on hover over its mark (and a tap on a touch screen)
  let popTimer = null;
  const hidePop = () => { clearTimeout(popTimer); editing = false; $("rv-notepop").style.display = "none"; };
  function showPop(m) {
    const n = noteList.find(x => x.id === m.dataset.note), pop = $("rv-notepop");
    if (!n || editing) return;
    clearTimeout(popTimer);
    pop.dataset.nid = n.id;
    // the note, then its exchange: the agent's answers (with "changed here" when it said where) and your replies
    const thread = n.thread && n.thread.length ? n.thread : n.answer ? [{who: "agent", text: n.answer, at: n.at}] : [];
    pop.innerHTML = `<div class="rv-meta">Note ${n.n} · ${n.noanswer ? "no answer from the agent: open again" : NSTATE[n.state] || n.state}</div>` +
      (m.dataset.where ? `<div class="rv-meta">Its text is gone from the page (changed): pinned ${esc(m.dataset.where)}. It was on “${esc(noteQuote(n, 80))}”</div>` : "") +
      (n.note ? esc(n.note) : '<i class="rv-meta">no note: the agent just looks at this text</i>') +
      thread.map(e => `<div class="rv-nans ${e.who === "owner" ? "owner" : "agent"}"><b>${e.who === "owner" ? "You" : "Agent"}${e.state ? " (" + esc(e.state) + ")" : ""}:</b> ${jumpLinks(e.text)}` +
        (e.at ? ` <a class="rv-jump" href="${attr(e.at)}" data-jump="${attr(e.at.replace(/^#/, ""))}">changed here →</a>` : "") + `</div>`).join("") +
      `<div class="rv-row"><button data-nop="reply" title="Answer the agent on this note; it goes with your next Send">reply</button>` +
      `<button data-nop="edit">edit</button><button data-nop="state">${n.state === "done" ? "reopen" : "done"}</button>` +
      `<button data-nop="delete">delete</button></div>`;
    const r = m.getBoundingClientRect();
    pop.style.left = Math.max(scrollX + 4, Math.min(r.left + scrollX, scrollX + innerWidth - 330)) + "px";
    pop.style.top = r.bottom + scrollY + 4 + "px";
    pop.style.display = "block";
  }
  const NOTE_HIT = "mark.rv-note,.rv-svgnote,.rv-svgpin";
  document.addEventListener("mouseover", e => {
    const m = e.target.closest && e.target.closest(NOTE_HIT);
    if (m) return showPop(m);
    if (editing || e.target.closest && e.target.closest("#rv-notepop")) return clearTimeout(popTimer);
    if ($("rv-notepop").style.display === "block") clearTimeout(popTimer), popTimer = setTimeout(hidePop, 400);
  });
  document.addEventListener("click", e => {
    const m = e.target.closest && e.target.closest(NOTE_HIT);
    if (m && window.getSelection().isCollapsed) showPop(m);
  });
  $("rv-notepop").addEventListener("click", e => {
    const a = e.target.closest(".rv-jump");
    if (a) {   // "changed here →", or a [link](#id) in an answer
      e.preventDefault();
      const el = jumpTarget(a.dataset.jump);
      if (!el) return a.classList.add("rv-broken"), a.title = GONE;
      return hidePop(), go(el);
    }
    const b = e.target.closest("[data-nop]");
    if (b) noteOp($("rv-notepop").dataset.nid, b.dataset.nop);
  });
  // E3a: the reply of a run that had notes starts with "Notes: ✓1 ○2 3?"; a number scrolls to its note and opens it
  function notesResultHtml(list) {
    return `<div class="rv-npoint">Notes: ${list.map(r => `<a class="rv-nres ${r.noanswer ? "noanswer" : r.state}" data-nres="${attr(r.id)}" href="#" ` +
      `title="${r.noanswer ? "no answer: open again" : r.state}: open the note">${r.state === "done" ? "✓" : r.noanswer ? "?" : "○"}${r.n}</a>`).join("")}` +
      ` <span class="rv-meta">(answers on the notes)</span></div>`;
  }
  $("rv-thread").addEventListener("click", e => {
    const a = e.target.closest(".rv-nres");
    if (!a) return;
    e.preventDefault();
    const n = noteList.find(x => x.id === a.dataset.nres);
    if (!n) return a.classList.add("rv-broken"), a.title = "This note is gone: deleted (by you, or before 2026-11-17 by a later run)";
    const m = noteMark(n.id);
    if (!m) return noteOp(n.id, "go");   // in a file, or moved: its line, or nothing to show but the list
    go(m);
    setTimeout(() => showPop(m), 400);    // after the scroll
  });
  // Send notes: the open notes go into the message box as chips
  function showNotePins() {
    const box = $("rv-notechips");
    box.style.display = notePins.length ? "flex" : "none";
    box.innerHTML = notePins.map(id => noteList.find(n => n.id === id)).filter(Boolean).map(n =>
      `<span class="rv-nchip" title="${attr(n.text + (n.note ? "\n\n" + n.note : ""))}"><span>📌 ${n.n} · ${esc(n.note ? n.note.replace(/\s+/g, " ").slice(0, 40) : noteQuote(n, 40))}</span>` +
      `<button data-unpin="${attr(n.id)}" title="Leave this note out of this message (it stays open)">&times;</button></span>`).join("");
  }
  $("rv-notechips").addEventListener("click", e => {
    const b = e.target.closest("[data-unpin]");
    if (b) notePins = notePins.filter(id => id !== b.dataset.unpin), showNotePins();
  });
  $("rv-notesend").onclick = () => {
    notePins = noteList.filter(n => n.state === "open").sort((x, y) => x.n - y.n).map(n => n.id);
    showNotePins();
    $("rv-text").focus();
  };
  $("rv-noteclear").onclick = () => {
    const k = noteList.filter(n => n.state === "done").length;
    if (k && confirm(`Delete the ${k} done note${k === 1 ? "" : "s"} and the agent's answers on them?`)) noteApi({op: "clear"});
  };
  const notesHtml = list => `<details class="rv-sel"><summary>📌 Sticky note${list.length === 1 ? "" : "s"} ${list.map(n => n.n).join(", ")}</summary>` +
    list.map(n => `<div class="rv-quote"><b>${n.n}</b> “${esc(n.text)}”${n.note ? "\n→ " + esc(n.note) : ""}</div>`).join("") + "</details>";
  // the box takes a link (as before) or a keyword: matching agents of this tree are listed to pick from
  const isLink = s => /^(https?:|[\/~.])/.test(s) || /index\.html?$/i.test(s);
  let collSeq = 0;
  function collSearch() {
    const v = $("rv-colllink").value.trim(), n = ++collSeq;
    if (!v || isLink(v)) { $("rv-collres").innerHTML = ""; return; }
    fetch("/_review/colleague_search?agent=" + encodeURIComponent(AGENT) + "&q=" + encodeURIComponent(v))
      .then(r => r.json()).then(r => {
        if (n !== collSeq) return;      // a newer keystroke is already searching
        $("rv-collres").innerHTML = r.results.length ? r.results.map(c =>
          `<div class="rv-hit"><span class="rv-hitx" title="${attr(c.path + " " + c.title + " (" + c.why + ")")}">` +
          `<b>${esc(c.path || "top agent")}</b> ${esc(c.title)} <i>${esc(c.why)}</i></span>` +
          (c.added ? `<i>already a colleague</i>` : `<button data-add="${attr(c.path || "/")}">+ Add</button>`) + "</div>").join("")
          : "<div>No agent matches.</div>";
      });
  }
  $("rv-colladd").onclick = () => {
    const add = $("rv-colllink").value.trim();
    if (!add) return;
    if (!isLink(add)) return collSearch();
    api("colleague", {add}).then(r => { if (r.error) alert(r.error); else $("rv-colllink").value = ""; refresh(); });
  };
  $("rv-colllink").oninput = collSearch;
  $("rv-colllink").onkeydown = e => { if (e.key === "Enter") $("rv-colladd").click(); };
  $("rv-collres").addEventListener("click", e => {
    const b = e.target.closest("[data-add]");
    if (b) api("colleague", {add: b.dataset.add}).then(r => {
      if (r.error) alert(r.error); else { $("rv-colllink").value = ""; $("rv-collres").innerHTML = ""; }
      refresh();
    });
  });
  $("rv-colllist").addEventListener("click", e => {
    const b = e.target.closest("[data-coll]"), m = e.target.closest("[data-mode]");
    if (b) post("colleague", {remove: b.dataset.coll});
    if (m && (m.dataset.next !== "all" || confirm(`Let this agent edit everything in ${m.dataset.mode || "the tree's top agent"}? ` +
        "That includes the folders of every agent inside it, even while they run.")))
      post("colleague", {mode: m.dataset.mode, value: m.dataset.next});
  });
  $("rv-once").onclick = () => grant(false);
  $("rv-always").onclick = () => grant(true);
  $("rv-dismiss").onclick = () => post("dismiss", {});
  try {
    if (sessionStorage.getItem("rv-open")) {
      const t = sessionStorage.getItem("rv-top");
      if (t !== null) keepTop = +t;
      sessionStorage.removeItem("rv-open"); sessionStorage.removeItem("rv-top");
      $("rv-btn").click();
    }
  } catch (e) {}
  refresh();

  // A favorite star before the page's title: the same favorites.json as the agent list's stars.
  (function () {
    const h = document.querySelector("h1") || document.querySelector("#dirai-card > summary");
    if (!h) return;
    const s = document.createElement("button");
    s.id = "rv-pagestar";
    s.style.cssText = "border:0;background:none;padding:0 6px 0 0;font-size:inherit;line-height:1;cursor:pointer;color:#999";
    const draw = on => {
      s.dataset.on = on ? "1" : "";
      s.style.color = on ? "#e0a800" : "#999";
      s.textContent = on ? "★" : "☆";
      s.title = on ? "Remove from favorites" : "Add to favorites";
    };
    s.onclick = e => {
      e.preventDefault(); e.stopPropagation();
      const on = !s.dataset.on;
      draw(on);
      api("favorite", {on}).then(res => { if (res.favorites) draw(res.favorites.includes(AGENT)); }).catch(() => draw(!on));
    };
    draw(false);
    h.prepend(s);
    api("favorites").then(f => draw(Array.isArray(f) && f.includes(AGENT))).catch(() => {});
  })();
})();
