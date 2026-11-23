/* Run code from a reply in the browser, for free: JavaScript or Python (Pyodide) inside a sandboxed iframe
   with no access to the page, cookies or the account. Nothing runs on the server and nothing is billed. */
(function () {
  "use strict";
  var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/";
  var LANGS = { js: "js", javascript: "js", node: "js", py: "py", python: "py", python3: "py" };
  function blocks(text) {
    var out = [];
    var re = /```([A-Za-z0-9_+-]*)[^\n]*\n([\s\S]*?)```/g;
    var m;
    while ((m = re.exec(String(text || ""))) && out.length < 4) {
      var lang = LANGS[(m[1] || "").toLowerCase()];
      if (lang && m[2].trim()) out.push({ lang: lang, code: m[2] });
    }
    return out;
  }
  function frameDoc(nonce) {
    // Runs inside an opaque-origin sandbox. Output goes back by postMessage only.
    return "<!doctype html><meta charset=utf-8><script>(function(){var N=" + JSON.stringify(nonce) + ";" +
      "function send(t,v){parent.postMessage({simkoRun:N,type:t,text:String(v)},'*')}" +
      "function fmt(a){return Array.prototype.map.call(a,function(x){try{return typeof x==='string'?x:JSON.stringify(x)}catch(e){return String(x)}}).join(' ')}" +
      "console.log=function(){send('out',fmt(arguments))};console.error=console.warn=function(){send('err',fmt(arguments))};" +
      "window.onerror=function(m){send('err',m)};" +
      "window.addEventListener('message',function(e){var d=e.data||{};if(d.simkoRun!==N)return;" +
      "if(d.lang==='js'){try{var r=(0,eval)(d.code);if(r!==undefined)send('out',fmt([r]))}catch(err){send('err',err&&err.stack||err)}send('done','')}" +
      "else{send('status','Loading Python (first run downloads about 10 MB)…');var s=document.createElement('script');s.src=" + JSON.stringify(PYODIDE + "pyodide.js") + ";" +
      "s.onerror=function(){send('err','Python could not load.');send('done','')};" +
      "s.onload=function(){loadPyodide({indexURL:" + JSON.stringify(PYODIDE) + ",stdout:function(t){send('out',t)},stderr:function(t){send('err',t)}}).then(function(py){send('status','Running…');" +
      "return py.loadPackagesFromImports(d.code).then(function(){return py.runPythonAsync(d.code)}).then(function(r){if(r!==undefined&&r!==null)send('out',String(r))})}).catch(function(err){send('err',err&&err.message||err)}).then(function(){send('done','')})};" +
      "document.head.appendChild(s)}});send('ready','')})()<\/script>";
  }
  function run(block, out, button) {
    var nonce = "r" + Math.random().toString(36).slice(2);
    var frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("title", "Code sandbox");
    frame.style.display = "none";
    out.hidden = false;
    out.textContent = "Starting…";
    button.disabled = true;
    var lines = [];
    var limit = block.lang === "py" ? 120000 : 15000;
    var timer = null;
    function finish(note) {
      window.removeEventListener("message", onMsg);
      clearTimeout(timer);
      if (note) lines.push(note);
      out.textContent = lines.length ? lines.join("\n") : "Done. Nothing was printed.";
      button.disabled = false;
      if (frame.parentNode) frame.parentNode.removeChild(frame);
    }
    function onMsg(e) {
      var d = e.data || {};
      if (e.source !== frame.contentWindow || d.simkoRun !== nonce) return;
      if (d.type === "ready") { frame.contentWindow.postMessage({ simkoRun: nonce, lang: block.lang, code: block.code }, "*"); return; }
      if (d.type === "status") { out.textContent = d.text; return; }
      if (d.type === "done") { finish(""); return; }
      lines.push((d.type === "err" ? "Error: " : "") + d.text);
      if (lines.length > 500) finish("(Output cut at 500 lines.)");
      else out.textContent = lines.join("\n");
    }
    window.addEventListener("message", onMsg);
    timer = setTimeout(function () { finish("(Stopped after " + Math.round(limit / 1000) + " seconds.)"); }, limit);
    frame.srcdoc = frameDoc(nonce);
    document.body.appendChild(frame);
  }
  function attach(text) {
    var reply = document.getElementById("reply-bubble");
    if (!reply) return;
    var box = document.getElementById("codeRunBox");
    if (!box) {
      box = document.createElement("div");
      box.id = "codeRunBox";
      reply.parentNode.insertBefore(box, reply.nextSibling);
    }
    box.replaceChildren();
    var found = blocks(text);
    box.hidden = !found.length;
    found.forEach(function (block, i) {
      var row = document.createElement("div");
      row.className = "codeRunRow";
      var b = document.createElement("button");
      b.type = "button";
      b.className = "codeRunBtn";
      b.textContent = "Run " + (block.lang === "py" ? "Python" : "JavaScript") + (found.length > 1 ? " block " + (i + 1) : "") + " here";
      var out = document.createElement("pre");
      out.className = "codeRunOut";
      out.hidden = true;
      out.setAttribute("role", "status");
      b.addEventListener("click", function () { run(block, out, b); });
      row.appendChild(b);
      row.appendChild(out);
      box.appendChild(row);
    });
  }
  window.simkoCodeRun = { attach: attach, blocks: blocks };
})();
