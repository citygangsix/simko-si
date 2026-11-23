/* Extra Simko SI screens. Loaded only when a platform flag is on. */
(function () {
  function $(id) { return document.getElementById(id); }
  function flags() { return window.simkoPlatformFlags || {}; }
  function token() {
    try { return sessionStorage.getItem("podcoderToken") || window.simcoUserToken || ""; }
    catch (e) { return window.simcoUserToken || ""; }
  }
  function signedIn() {
    return document.documentElement.getAttribute("data-simko-signed") === "1" || !!token();
  }
  function post(body) {
    return fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token: token() }, body))
    }).then(function (res) { return res.json(); });
  }
  function show(id) {
    ["paywallCard", "usagePage", "approvalCard", "searchCard", "memoryCard", "routineCard", "imageCard", "shareCard", "oauthCard", "vaultCard", "connectorCard", "agentBoard", "teamCard", "callCard", "browseCard", "storeCard", "codeCard"].forEach(function (name) {
      var card = $(name);
      if (card) card.hidden = name !== id;
    });
    var stage = $("platformStage");
    if (stage) stage.hidden = false;
  }
  function hide() {
    var stage = $("platformStage");
    if (stage) stage.hidden = true;
  }
  function planLabel(data) {
    return (data && data.plan_label) ? data.plan_label : "$9.99/month";
  }
  function billingProvider(data) {
    if (data && data.billing && data.billing.provider) return data.billing.provider;
    return "stripe";
  }
  function showPaywall(data) {
    var lead = $("paywallLead");
    if (lead) {
      var used = data && data.used != null ? data.used : 5;
      lead.textContent = used + " messages are used. Pictures stay on the paid plan. Nothing is charged until you tap pay.";
    }
    var buy = $("paywallBuy");
    if (buy) buy.textContent = planLabel(data);
    var note = $("paywallNote");
    if (note) note.textContent = "";
    show("paywallCard");
  }
  function paintUsage(data) {
    var summary = $("usageSummary");
    var list = $("usageList");
    if (summary) {
      if (data.status === "paid") summary.textContent = "This month is paid at " + planLabel(data) + ". " + data.used + " messages so far.";
      else summary.textContent = data.used + " of " + data.limit + " messages used. " + data.remaining + " left.";
    }
    var portal = $("usagePortal");
    if (portal) {
      var showPortal = data.status === "paid" && billingProvider(data) === "stripe";
      portal.hidden = !showPortal;
    }
    if (!list) return;
    list.replaceChildren();
    (data.events || []).forEach(function (event) {
      var item = document.createElement("li");
      var when = new Date((event.created_at || 0) * 1000);
      item.textContent = (event.kind === "voice" ? "Voice turn" : "Message") + " · " + when.toLocaleString();
      list.appendChild(item);
    });
    var ledger = data.image_ledger;
    if (ledger && ledger.month_billed_count) {
      var pics = document.createElement("li");
      pics.textContent = "Pictures this month: " + ledger.month_billed_count + ", " + ledger.month_billed_label + " (Grok's cost, added to your bill)";
      list.appendChild(pics);
    }
    if (!(data.events || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "No messages yet.";
      list.appendChild(empty);
    }
  }
  var pendingApproval = null;
  function paintAudit(rows) {
    var list = $("auditList");
    if (!list) return;
    list.replaceChildren();
    (rows || []).forEach(function (row) {
      var item = document.createElement("li");
      item.textContent = row.summary;
      list.appendChild(item);
    });
    if (!(rows || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "Nothing has been approved or declined yet.";
      list.appendChild(empty);
    }
  }
  function showApproval(approval, retry) {
    pendingApproval = { approval: approval, retry: retry };
    var summary = $("approvalSummary");
    if (summary) summary.textContent = approval.summary || "Simko SI is waiting for you.";
    post({ op: "audit" }).then(function (data) { paintAudit(data.audit || []); });
    show("approvalCard");
  }
  function showSources(sources) {
    var list = $("searchSources");
    if (!list) return;
    list.replaceChildren();
    (sources || []).forEach(function (url) {
      var item = document.createElement("li");
      var link = document.createElement("a");
      link.href = url;
      link.textContent = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.appendChild(link);
      list.appendChild(item);
    });
    if (!(sources || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "No safe sources came back.";
      list.appendChild(empty);
    }
    show("searchCard");
  }
  function paintAgentTools(node, data) {
    node.replaceChildren();
    var bits = [];
    var runs = data.code_runs || [];
    var pages = (data.pages || []).filter(function (page) { return page && page.ok; });
    var sources = data.sources || [];
    if (runs.length) bits.push(runs.length === 1 ? "ran 1 code block" : "ran " + runs.length + " code blocks");
    if (pages.length) bits.push(pages.length === 1 ? "read 1 page" : "read " + pages.length + " pages");
    if (sources.length) bits.push(sources.length === 1 ? "1 source" : sources.length + " sources");
    if (data.cost_ticks) bits.push("$" + (data.cost_ticks / 1e10).toFixed(4));
    if (!bits.length) return;
    var head = document.createElement("p");
    head.textContent = "Tools: " + bits.join(", ");
    node.appendChild(head);
    sources.slice(0, 6).forEach(function (src) {
      var url = typeof src === "string" ? src : (src && src.url) || "";
      if (!/^https?:\/\//.test(url)) return;
      var link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = (src && src.title) || url;
      var line = document.createElement("p");
      line.appendChild(link);
      node.appendChild(line);
    });
  }

  /* Code tab: Grok writes a small static project, the browser runs it in a sandboxed iframe and tests it. */
  var codeJob = null;
  var codeRunId = 0;
  function codeStatus(text) { var n = $("codeStatus"); if (n) n.textContent = text; }
  function codeList(id, items, render) {
    var list = $(id);
    if (!list) return;
    list.replaceChildren();
    (items || []).forEach(function (item) {
      var li = document.createElement("li");
      render(li, item);
      list.appendChild(li);
    });
  }
  function codeHarness(runId, tests) {
    // Runs inside the sandboxed preview (opaque origin, no site cookies). Posts results to the parent.
    return "(function(){var RUN=" + JSON.stringify(runId) + ";var TESTS=" + JSON.stringify(tests || []).replace(/</g, "\\u003c") + ";" +
      "var errors=[];window.addEventListener('error',function(e){errors.push(String(e.message||e.error||'error'));});" +
      "function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}" +
      "function find(sel){return new Promise(function(res,rej){var n=0;(function look(){var el=null;try{el=document.querySelector(sel);}catch(e){return rej(new Error('Bad selector '+sel));}if(el)return res(el);if(++n>40)return rej(new Error('Not found: '+sel));setTimeout(look,50);})();});}" +
      "function textOf(el){return ('value' in el && el.tagName!=='BUTTON')?String(el.value):String(el.textContent||'');}" +
      "async function step(s){if(s.action==='wait'){await sleep(Math.min(2000,Number(s.value)||200));return;}var el=await find(s.selector);" +
      "if(s.action==='click'){el.click();await sleep(30);return;}" +
      "if(s.action==='type'){el.focus();el.value=s.value;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));await sleep(30);return;}" +
      "if(s.action==='expect_text'){var want=String(s.value).trim();for(var i=0;i<20;i++){var got=textOf(el).trim();if(got===want||got.indexOf(want)>=0&&want!=='')return;await sleep(50);}throw new Error('Expected \"'+want+'\" in '+s.selector+', saw \"'+textOf(el).trim().slice(0,80)+'\"');}" +
      "throw new Error('Unknown step '+s.action);}" +
      "async function run(){await sleep(150);var results=[];for(var t=0;t<TESTS.length;t++){var test=TESTS[t];var r={name:test.name,passed:true,detail:'passed'};" +
      "try{for(var k=0;k<test.steps.length;k++){await step(test.steps[k]);}}catch(e){r.passed=false;r.detail=String(e.message||e);}results.push(r);}" +
      "parent.postMessage({simkoCode:RUN,results:results,errors:errors.slice(0,10)},'*');}" +
      "if(document.readyState==='complete')run();else window.addEventListener('load',run);})();";
  }
  function codeSrcdoc(job, runId) {
    var files = {};
    (job.files || []).forEach(function (f) { files[f.path] = f.content; });
    var html = files[job.entry] || "";
    var escapeScript = function (code) { return String(code).replace(/<\/script/gi, "<\\/script"); };
    html = html.replace(/<link\b[^>]*href=["']([^"']+)["'][^>]*>/gi, function (tag, href) {
      if (!/stylesheet/i.test(tag) || files[href] == null) return tag;
      return "<style>" + String(files[href]).replace(/<\/style/gi, "<\\/style") + "</style>";
    });
    html = html.replace(/<script\b([^>]*)src=["']([^"']+)["']([^>]*)>\s*<\/script>/gi, function (tag, a, src, b) {
      if (files[src] == null) return tag;
      return "<script" + a + b + ">" + escapeScript(files[src]) + "</scr" + "ipt>";
    });
    var harness = "<script>" + escapeScript(codeHarness(runId, job.tests)) + "</scr" + "ipt>";
    return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, harness + "</body>") : html + harness;
  }
  function paintCodeJob(job) {
    codeJob = job;
    if (!job) return;
    var engineNote = job.engine === "cursor" ? " (Cursor)" : "";
    var busy = job.status === "planning" || job.status === "fixing";
    codeStatus((job.title && !busy ? job.title + ": " : "") + job.status_label + (busy ? "…" : "") + engineNote + (job.error ? " (" + job.error + ")" : "") + (job.cost_ticks ? " · xAI cost " + job.cost_label : ""));
    codeList("codePlan", job.plan, function (li, step) { li.textContent = step; });
    codeList("codeChecks", job.check_errors, function (li, err) { li.className = "bad"; li.textContent = err; });
    codeList("codeTests", job.test_results, function (li, r) {
      li.className = r.passed ? "ok" : "bad";
      li.textContent = (r.passed ? "✓ " : "✗ ") + r.name + (r.passed ? "" : ": " + r.detail);
    });
    var files = job.files || [];
    var body = $("codeFilesBody");
    if (body) {
      body.replaceChildren();
      files.forEach(function (f) {
        var h = document.createElement("p");
        h.textContent = f.path + " · " + f.bytes + " bytes";
        var pre = document.createElement("pre");
        pre.textContent = f.content;
        body.append(h, pre);
      });
    }
    $("codeFiles").hidden = !files.length;
    $("codeZip").hidden = !files.length;
    $("codeRetest").hidden = !files.length || job.engine !== "grok";
    $("codeFix").hidden = !(job.can_fix);
  }
  function runCodePreview(job) {
    var old = $("codePreview");
    if (!old || !job || !(job.files || []).length || job.engine !== "grok") return;
    if (job.status === "checks_failed") { old.hidden = true; return; }
    // A fresh sandboxed frame for every run: no state or history carries over between builds.
    var frame = document.createElement("iframe");
    frame.id = "codePreview";
    frame.title = "Project preview";
    frame.setAttribute("sandbox", "allow-scripts");
    old.replaceWith(frame);
    codeRunId += 1;
    var runId = job.id + ":" + codeRunId;
    frame.hidden = false;
    codeStatus("Running " + (job.tests || []).length + " test(s) in the sandbox…");
    var finished = false;
    function onMessage(event) {
      if (event.source !== frame.contentWindow || !event.data || event.data.simkoCode !== runId) return;
      finished = true;
      window.removeEventListener("message", onMessage);
      post({ op: "code-verify", job_id: job.id, results: event.data.results, errors: event.data.errors }).then(function (data) {
        if (data.ok) paintCodeJob(data.job); else codeStatus(data.error || "Could not save the test results.");
      });
    }
    window.addEventListener("message", onMessage);
    setTimeout(function () {
      if (finished) return;
      window.removeEventListener("message", onMessage);
      post({ op: "code-verify", job_id: job.id, results: [], errors: ["The page did not finish its tests within 20 seconds."] }).then(function (data) {
        if (data.ok) paintCodeJob(data.job);
      });
    }, 20000);
    frame.srcdoc = codeSrcdoc(job, runId);
  }
  // Builds and fixes run on the server after the reply; poll until Grok is done (up to 6 minutes).
  function waitForCodeJob(job) {
    return new Promise(function (resolve) {
      var started = Date.now();
      (function tick() {
        if (!job || (job.status !== "planning" && job.status !== "fixing")) { resolve(job); return; }
        if (Date.now() - started > 360000) { resolve(job); return; }
        setTimeout(function () {
          post({ op: "code-job", job_id: job.id }).then(function (data) {
            if (data.ok && data.job) { job = data.job; paintCodeJob(job); }
            tick();
          }).catch(function () { tick(); });
        }, 3000);
      })();
    });
  }
  function loadCodeJobs() {
    post({ op: "code-jobs" }).then(function (data) {
      if (!data.ok) { codeStatus(data.error || "The Code tab is not available."); return; }
      var cursor = data.engines && data.engines.cursor;
      var opt = document.querySelector('#codeEngine option[value="cursor"]');
      if (opt && cursor) opt.textContent = cursor.ready ? (cursor.allow_launch ? "Cursor cloud agent (paid)" : "Cursor cloud agent (dry run)") : "Cursor cloud agent (no key, dry run)";
      codeList("codeJobs", (data.jobs || []).slice(0, 6), function (li, job) {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = (job.title || job.prompt.slice(0, 40)) + " · " + job.status_label;
        b.addEventListener("click", function () { paintCodeJob(job); if (job.status === "built" || job.status === "verified" || job.status === "tests_failed") runCodePreview(job); });
        li.appendChild(b);
      });
    });
  }
  function bindCode() {
    var open = $("codeOpen");
    if (open) open.hidden = false;
    if (!open || open.dataset.bound) return;
    open.dataset.bound = "1";
    open.addEventListener("click", function () { show("codeCard"); loadCodeJobs(); });
    $("codeClose").addEventListener("click", hide);
    $("codeForm").addEventListener("submit", function (event) {
      event.preventDefault();
      var prompt = $("codePrompt").value.trim();
      if (!prompt) { codeStatus("Describe what to build first."); return; }
      var engine = $("codeEngine").value;
      var build = $("codeBuild");
      build.disabled = true;
      $("codePreview").hidden = true;
      codeList("codeTests", [], function () {});
      codeStatus(engine === "cursor" ? "Preparing the Cursor request (dry run, nothing is launched)…" : "Grok is planning and writing the files…");
      post({ op: "code-start", prompt: prompt, engine: engine, dry_run: engine === "cursor" }).then(function (data) {
        build.disabled = false;
        if (!data.ok) { codeStatus(data.error || "The build failed."); return; }
        paintCodeJob(data.job);
        if (data.job.engine === "grok") {
          build.disabled = true;
          waitForCodeJob(data.job).then(function (job) {
            build.disabled = false;
            paintCodeJob(job);
            runCodePreview(job);
            loadCodeJobs();
          });
          return;
        }
        if (data.job.engine === "cursor") {
          var pre = document.createElement("pre");
          pre.textContent = JSON.stringify(data.job.cursor || {}, null, 2);
          var body = $("codeFilesBody");
          if (body) { body.replaceChildren(pre); $("codeFiles").hidden = false; $("codeFiles").open = true; }
        }
        runCodePreview(data.job);
        loadCodeJobs();
      }).catch(function () { build.disabled = false; codeStatus("The build request did not finish. Try again."); });
    });
    $("codeRetest").addEventListener("click", function () { if (codeJob) runCodePreview(codeJob); });
    $("codeFix").addEventListener("click", function () {
      if (!codeJob) return;
      var btn = $("codeFix");
      btn.disabled = true;
      codeStatus("Grok is fixing the failures…");
      post({ op: "code-fix", job_id: codeJob.id }).then(function (data) {
        if (!data.ok) { btn.disabled = false; codeStatus(data.error || "The fix failed."); return; }
        paintCodeJob(data.job);
        waitForCodeJob(data.job).then(function (job) {
          btn.disabled = false;
          paintCodeJob(job);
          runCodePreview(job);
        });
      });
    });
    $("codeZip").addEventListener("click", function () {
      if (!codeJob) return;
      post({ op: "code-zip", job_id: codeJob.id }).then(function (data) {
        if (!data.ok) { codeStatus(data.error || "The zip could not be made."); return; }
        var bytes = Uint8Array.from(atob(data.zip_b64), function (c) { return c.charCodeAt(0); });
        var url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
        var a = document.createElement("a");
        a.href = url;
        a.download = data.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      });
    });
    $("cursorCheck").addEventListener("click", function () {
      post({ op: "cursor-check" }).then(function (data) {
        var c = data.cursor || {};
        codeStatus(data.ok ? (c.ok ? "Cursor key works" + (c.account ? " for " + c.account : "") + "." : (c.message || c.error || "No Cursor key is set up.")) : (data.error || "Could not check."));
      });
    });
  }

  function boot() {
    if (flags().code) bindCode();
    var searchClose = $("searchClose");
    if (flags().search && searchClose && !searchClose.dataset.bound) {
      searchClose.dataset.bound = "1";
      searchClose.addEventListener("click", hide);
    }
    if (flags().store) {
      var storeOpen = $("storeOpen");
      if (storeOpen) storeOpen.hidden = false;
      if (storeOpen && !storeOpen.dataset.bound) {
        storeOpen.dataset.bound = "1";
        storeOpen.addEventListener("click", function () {
          post({ op: "store-steps" }).then(function (data) {
            var list = $("storeSteps");
            if (!list) return;
            list.replaceChildren();
            (data.steps || []).forEach(function (step) {
              var item = document.createElement("li");
              item.textContent = step;
              list.appendChild(item);
            });
            show("storeCard");
          });
        });
      }
      var storeClose = $("storeClose");
      if (storeClose && !storeClose.dataset.bound) {
        storeClose.dataset.bound = "1";
        storeClose.addEventListener("click", hide);
      }
    }
    if (flags().browse) {
      var browseOpen = $("browseOpen");
      if (browseOpen) browseOpen.hidden = false;
      if (browseOpen && !browseOpen.dataset.bound) {
        browseOpen.dataset.bound = "1";
        browseOpen.addEventListener("click", function () { show("browseCard"); });
      }
      var browseForm = $("browseForm");
      if (browseForm && !browseForm.dataset.bound) {
        browseForm.dataset.bound = "1";
        browseForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({ op: "browse", url: $("browseUrl").value }).then(function (data) {
            $("browseText").textContent = data.ok ? data.text : (data.error || "That page could not be read.");
          });
        });
      }
      var browseClose = $("browseClose");
      if (browseClose && !browseClose.dataset.bound) {
        browseClose.dataset.bound = "1";
        browseClose.addEventListener("click", hide);
      }
    }
    if (flags().calls) {
      var callOpen = $("callOpen");
      if (callOpen) callOpen.hidden = false;
      if (callOpen && !callOpen.dataset.bound) {
        callOpen.dataset.bound = "1";
        callOpen.addEventListener("click", function () {
          post({ op: "call-status" }).then(function (data) {
            if ($("callReason") && data.reason) $("callReason").textContent = data.reason;
            var start = $("callStart");
            if (start) start.disabled = true;
            show("callCard");
          });
        });
      }
      var callClose = $("callClose");
      if (callClose && !callClose.dataset.bound) {
        callClose.dataset.bound = "1";
        callClose.addEventListener("click", hide);
      }
    }
    if (flags().team) {
      var teamOpen = $("teamOpen");
      if (teamOpen) teamOpen.hidden = false;
      if (teamOpen && !teamOpen.dataset.bound) {
        teamOpen.dataset.bound = "1";
        teamOpen.addEventListener("click", function () {
          post({ op: "team" }).then(function (data) {
            var list = $("teamList");
            if (!list) return;
            list.replaceChildren();
            (data.members || []).forEach(function (member) {
              var item = document.createElement("li");
              item.textContent = member.email + " · " + member.role;
              list.appendChild(item);
            });
            show("teamCard");
          });
        });
      }
      var teamForm = $("teamForm");
      if (teamForm && !teamForm.dataset.bound) {
        teamForm.dataset.bound = "1";
        teamForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({ op: "invite", email: $("teamEmail").value, role: $("teamRole").value }).then(function (data) {
            if (!data.ok) return;
            $("teamNote").textContent = "Invite ready for " + data.invite.email + " as " + data.invite.role + ".";
          });
        });
      }
      var teamClose = $("teamClose");
      if (teamClose && !teamClose.dataset.bound) {
        teamClose.dataset.bound = "1";
        teamClose.addEventListener("click", hide);
      }
    }
    if (flags().agents) {
      var agentOpen = $("agentOpen");
      if (agentOpen) agentOpen.hidden = false;
      function paintAgents(rows) {
        var board = $("agentPanes");
        if (!board) return;
        board.replaceChildren();
        (rows || []).forEach(function (agent, index) {
          var pane = document.createElement("article");
          pane.className = "agentPane";
          var title = document.createElement("h3");
          title.textContent = agent.name;
          var persona = document.createElement("p");
          persona.textContent = agent.persona;
          var reply = document.createElement("p");
          reply.className = "agentReply";
          reply.textContent = "";
          var box = document.createElement("input");
          box.type = "text";
          box.placeholder = "Message " + agent.name;
          var send = document.createElement("button");
          send.type = "button";
          send.textContent = "Ask";
          var cancel = document.createElement("button");
          cancel.type = "button";
          cancel.textContent = "Cancel";
          cancel.disabled = true;
          var control = null;
          send.addEventListener("click", function () {
            var text = box.value.trim();
            if (!text) return;
            if (control) control.abort();
            control = new AbortController();
            cancel.disabled = false;
            reply.textContent = "";
            tools.replaceChildren();
            reply.textContent = "Working on it…";
            var started = false;
            fetch("/api/agent-stream", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ token: token(), agent_id: agent.id, text: text }),
              signal: control.signal
            }).then(function (res) {
              var type = res.headers.get("Content-Type") || "";
              if (!res.ok || type.indexOf("text/event-stream") < 0) {
                cancel.disabled = true;
                return res.json().catch(function () { return {}; }).then(function (data) {
                  reply.textContent = data.error || ("The agent could not answer (" + res.status + ").");
                });
              }
              var reader = res.body && res.body.getReader ? res.body.getReader() : null;
              if (!reader) return;
              var decoder = new TextDecoder();
              var pending = "";
              function pump() {
                return reader.read().then(function (chunk) {
                  if (chunk.done) {
                    cancel.disabled = true;
                    return;
                  }
                  pending += decoder.decode(chunk.value, { stream: true });
                  var blocks = pending.split("\n\n");
                  pending = blocks.pop() || "";
                  blocks.forEach(function (block) {
                    var line = block.trim();
                    if (line.indexOf("data:") !== 0) return;
                    var data = {};
                    try { data = JSON.parse(line.slice(5)); } catch (e) { return; }
                    if (data.agent_id !== agent.id) return;
                    if (data.error) { reply.textContent = data.error; return; }
                    if (data.done) { paintAgentTools(tools, data); return; }
                    if (!data.delta) return;
                    if (!started) { reply.textContent = ""; started = true; }
                    reply.textContent += data.delta;
                  });
                  return pump();
                });
              }
              return pump();
            }).catch(function (e) {
              cancel.disabled = true;
              if (!(e && e.name === "AbortError") && !started) reply.textContent = "The agent could not be reached. Try again in a moment.";
            });
          });
          cancel.addEventListener("click", function () {
            if (control) control.abort();
            cancel.disabled = true;
          });
          var tools = document.createElement("div");
          tools.className = "agentTools";
          pane.append(title, persona, reply, tools, box, send, cancel);
          if (index > 0) {
            var hand = document.createElement("button");
            hand.type = "button";
            hand.textContent = "Hand to " + agent.name;
            hand.addEventListener("click", function () {
              var text = window.prompt("Message to hand to " + agent.name) || "";
              if (!text) return;
              post({ op: "hand-agent", from_id: rows[0].id, to_id: agent.id, text: text });
            });
            pane.appendChild(hand);
          }
          board.appendChild(pane);
        });
      }
      if (agentOpen && !agentOpen.dataset.bound) {
        agentOpen.dataset.bound = "1";
        agentOpen.addEventListener("click", function () {
          post({ op: "agents" }).then(function (data) {
            if (!data.ok) return;
            paintAgents(data.agents || []);
            show("agentBoard");
          });
        });
      }
      var agentForm = $("agentForm");
      if (agentForm && !agentForm.dataset.bound) {
        agentForm.dataset.bound = "1";
        agentForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({ op: "create-agent", name: $("agentName").value, persona: $("agentPersona").value }).then(function (data) {
            if (data.ok) paintAgents(data.agents || []);
          });
        });
      }
      var agentClose = $("agentClose");
      if (agentClose && !agentClose.dataset.bound) {
        agentClose.dataset.bound = "1";
        agentClose.addEventListener("click", hide);
      }
    }
    if (flags().connectors) {
      var connectorOpen = $("connectorOpen");
      if (connectorOpen) connectorOpen.hidden = false;
      if (connectorOpen && !connectorOpen.dataset.bound) {
        connectorOpen.dataset.bound = "1";
        connectorOpen.addEventListener("click", function () {
          post({ op: "connectors" }).then(function (data) {
            var list = $("connectorList");
            if (!list) return;
            list.replaceChildren();
            (data.connectors || []).forEach(function (row) {
              if (!row.ready) return;
              var item = document.createElement("li");
              item.textContent = row.name + (row.connected ? " · Connected" : " · Not connected") + " ";
              var button = document.createElement("button");
              button.type = "button";
              button.textContent = row.connected ? "Disconnect" : "Connect " + row.name;
              button.addEventListener("click", function () {
                if (row.connected) {
                  post({ op: "connector-disconnect", provider: row.id }).then(function () {
                    item.textContent = row.name + " · Not connected";
                  });
                  return;
                }
                post({ op: "connector-start", provider: row.id }).then(function (started) {
                  if (started.url) window.location.href = started.url;
                });
              });
              item.appendChild(button);
              list.appendChild(item);
            });
            if (!list.children.length) {
              var empty = document.createElement("li");
              empty.textContent = "Connectors stay hidden until their client ids are set.";
              list.appendChild(empty);
            }
            show("connectorCard");
          });
        });
      }
      var connectorClose = $("connectorClose");
      if (connectorClose && !connectorClose.dataset.bound) {
        connectorClose.dataset.bound = "1";
        connectorClose.addEventListener("click", hide);
      }
    }
    if (flags().vault) {
      var vaultOpen = $("vaultOpen");
      if (vaultOpen) vaultOpen.hidden = false;
      function paintVault(items) {
        var list = $("vaultList");
        if (!list) return;
        list.replaceChildren();
        (items || []).forEach(function (item) {
          var row = document.createElement("li");
          row.textContent = item.label + " " + item.value + " ";
          var button = document.createElement("button");
          button.type = "button";
          button.textContent = "Reveal";
          button.addEventListener("click", function () {
            var phrase = window.prompt("Passphrase");
            if (!phrase) return;
            post({ op: "vault-reveal", item_id: item.id, passphrase: phrase }).then(function (data) {
              row.textContent = data.ok ? item.label + " " + data.value : (data.error || "Locked");
            });
          });
          row.appendChild(button);
          list.appendChild(row);
        });
      }
      if (vaultOpen && !vaultOpen.dataset.bound) {
        vaultOpen.dataset.bound = "1";
        vaultOpen.addEventListener("click", function () {
          post({ op: "vault-list" }).then(function (data) {
            if (!data.ok) return;
            paintVault(data.items || []);
            show("vaultCard");
          });
        });
      }
      var vaultForm = $("vaultForm");
      if (vaultForm && !vaultForm.dataset.bound) {
        vaultForm.dataset.bound = "1";
        vaultForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({
            op: "vault-put",
            label: $("vaultLabel").value,
            value: $("vaultValue").value,
            passphrase: $("vaultPass").value
          }).then(function () {
            post({ op: "vault-list" }).then(function (data) { if (data.ok) paintVault(data.items || []); });
          });
        });
      }
      var vaultClose = $("vaultClose");
      if (vaultClose && !vaultClose.dataset.bound) {
        vaultClose.dataset.bound = "1";
        vaultClose.addEventListener("click", hide);
      }
    }
    if (flags().oauth) {
      var oauthButtons = window.simkoOauth || {};
      var google = $("googleSignIn");
      var apple = $("appleSignIn");
      if (google) google.hidden = !oauthButtons.google;
      if (apple) apple.hidden = !oauthButtons.apple;
      if ((oauthButtons.google || oauthButtons.apple) && $("accountSignIn") && !$("accountSignIn").dataset.oauth) {
        $("accountSignIn").dataset.oauth = "1";
        $("accountSignIn").addEventListener("click", function () {
          setTimeout(function () { show("oauthCard"); }, 0);
        });
      }
      function begin(provider) {
        fetch("/api/platform", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ op: "oauth-start", provider: provider })
        }).then(function (res) { return res.json(); }).then(function (data) {
          if (data.url) window.location.href = data.url;
        });
      }
      if (google && !google.dataset.bound) {
        google.dataset.bound = "1";
        google.addEventListener("click", function () { begin("google"); });
      }
      if (apple && !apple.dataset.bound) {
        apple.dataset.bound = "1";
        apple.addEventListener("click", function () { begin("apple"); });
      }
      var oauthClose = $("oauthClose");
      if (oauthClose && !oauthClose.dataset.bound) {
        oauthClose.dataset.bound = "1";
        oauthClose.addEventListener("click", hide);
      }
    }
    if (flags().shares) {
      var shareOpen = $("shareOpen");
      if (shareOpen) shareOpen.hidden = false;
      var shareToken = "";
      if (shareOpen && !shareOpen.dataset.bound) {
        shareOpen.dataset.bound = "1";
        shareOpen.addEventListener("click", function () { show("shareCard"); });
      }
      var shareCreate = $("shareCreate");
      if (shareCreate && !shareCreate.dataset.bound) {
        shareCreate.dataset.bound = "1";
        shareCreate.addEventListener("click", function () {
          post({ op: "share-lifebook" }).then(function (data) {
            if (!data.ok) return;
            shareToken = data.share.token;
            $("shareUrl").textContent = data.share.url;
            $("shareRevoke").hidden = false;
          });
        });
      }
      var shareRevoke = $("shareRevoke");
      if (shareRevoke && !shareRevoke.dataset.bound) {
        shareRevoke.dataset.bound = "1";
        shareRevoke.addEventListener("click", function () {
          post({ op: "revoke-share", share_token: shareToken }).then(function (data) {
            if (!data.ok) return;
            $("shareUrl").textContent = "That link is revoked.";
            shareRevoke.hidden = true;
          });
        });
      }
      var shareClose = $("shareClose");
      if (shareClose && !shareClose.dataset.bound) {
        shareClose.dataset.bound = "1";
        shareClose.addEventListener("click", hide);
      }
    }
    if (flags().images) {
      var imageOpen = $("imageOpen");
      if (imageOpen) imageOpen.hidden = false;
      function paintImageCost(data) {
        var quote = $("imageQuote");
        var access = data && data.access;
        if (quote && access) quote.textContent = access.quote + (access.allowed ? " " + access.today + " of " + access.cap + " pictures today." : "");
        var btn = $("imageForm") && $("imageForm").querySelector("button[type=submit]");
        if (btn && access) btn.disabled = !access.allowed;
        var list = $("imageLedger");
        var ledger = data && data.ledger;
        if (!list || !ledger) return;
        list.replaceChildren();
        if (access && access.billed) {
          var total = document.createElement("li");
          total.textContent = "This month: " + ledger.month_billed_count + " pictures, " + ledger.month_billed_label + " added to your bill.";
          list.appendChild(total);
        }
        (ledger.rows || []).slice(0, 5).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = new Date(row.created_at * 1000).toLocaleString() + " · " + row.cost_label + (row.status === "owner_not_billed" ? " (Grok cost, not billed)" : " (on your bill)");
          list.appendChild(item);
        });
      }
      function paintImages(rows) {
        var grid = $("imageGrid");
        if (!grid) return;
        grid.replaceChildren();
        (rows || []).forEach(function (row) {
          var img = document.createElement("img");
          img.src = row.url;
          img.alt = row.prompt;
          grid.appendChild(img);
        });
      }
      if (imageOpen && !imageOpen.dataset.bound) {
        imageOpen.dataset.bound = "1";
        imageOpen.addEventListener("click", function () {
          post({ op: "images" }).then(function (data) {
            if (!data.ok) return;
            paintImages(data.images || []);
            paintImageCost(data);
            var status = $("imageStatus");
            if (status) status.textContent = "";
            show("imageCard");
          });
        });
      }
      var imageForm = $("imageForm");
      if (imageForm && !imageForm.dataset.bound) {
        imageForm.dataset.bound = "1";
        imageForm.addEventListener("submit", function (event) {
          event.preventDefault();
          var status = $("imageStatus");
          if (status) status.textContent = "Making the picture…";
          post({ op: "imagine", prompt: $("imagePrompt").value }).then(function (data) {
            if (data && !data.ok) {
              if (status) status.textContent = data.error || "No picture came back.";
              if (data.paywall && flags().paywall) showPaywall(data);
              return;
            }
            paintImages(data.images || []);
            paintImageCost(data);
            if (status && data.image) status.textContent = "Done. This picture cost " + data.image.cost_label + (data.image.charge_status !== "owner_not_billed" ? ", added to your bill." : " on your Grok key (not billed).");
          });
        });
      }
      var imageClose = $("imageClose");
      if (imageClose && !imageClose.dataset.bound) {
        imageClose.dataset.bound = "1";
        imageClose.addEventListener("click", hide);
      }
    }
    if (flags().routines) {
      var routineOpen = $("routineOpen");
      if (routineOpen) routineOpen.hidden = false;
      function paintRoutines(data) {
        var list = $("routineList");
        if (!list) return;
        list.replaceChildren();
        (data.deliveries || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.body;
          list.appendChild(item);
        });
        (data.routines || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.label + " at " + String(row.hour).padStart(2, "0") + ":" + String(row.minute).padStart(2, "0");
          list.appendChild(item);
        });
      }
      if (routineOpen && !routineOpen.dataset.bound) {
        routineOpen.dataset.bound = "1";
        routineOpen.addEventListener("click", function () {
          post({ op: "routines" }).then(function (data) {
            if (!data.ok) return;
            paintRoutines(data);
            show("routineCard");
          });
        });
      }
      var routineForm = $("routineForm");
      if (routineForm && !routineForm.dataset.bound) {
        routineForm.dataset.bound = "1";
        routineForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({
            op: "save-routine",
            kind: $("routineKind").value,
            hour: Number($("routineHour").value),
            minute: Number($("routineMinute").value)
          }).then(function () {
            post({ op: "routines" }).then(function (data) { if (data.ok) paintRoutines(data); });
          });
        });
      }
      var routineClose = $("routineClose");
      if (routineClose && !routineClose.dataset.bound) {
        routineClose.dataset.bound = "1";
        routineClose.addEventListener("click", hide);
      }
    }
    if (flags().memory) {
      var memoryOpen = $("memoryOpen");
      if (memoryOpen) memoryOpen.hidden = false;
      function paintMemories(rows) {
        var list = $("memoryList");
        if (!list) return;
        list.replaceChildren();
        (rows || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.fact + " ";
          var button = document.createElement("button");
          button.type = "button";
          button.textContent = "Delete";
          button.addEventListener("click", function () {
            post({ op: "forget", memory_id: row.id }).then(function (data) {
              if (data.ok) paintMemories(data.memories || []);
            });
          });
          item.appendChild(button);
          list.appendChild(item);
        });
        if (!(rows || []).length) {
          var empty = document.createElement("li");
          empty.textContent = "No memories yet.";
          list.appendChild(empty);
        }
      }
      if (memoryOpen && !memoryOpen.dataset.bound) {
        memoryOpen.dataset.bound = "1";
        memoryOpen.addEventListener("click", function () {
          post({ op: "memories" }).then(function (data) {
            if (!data.ok) return;
            paintMemories(data.memories || []);
            show("memoryCard");
          });
        });
      }
      var memoryClose = $("memoryClose");
      if (memoryClose && !memoryClose.dataset.bound) {
        memoryClose.dataset.bound = "1";
        memoryClose.addEventListener("click", hide);
      }
    }
    if (flags().approvals) {
      var yes = $("approvalYes");
      var no = $("approvalNo");
      var close = $("approvalClose");
      if (close && !close.dataset.bound) {
        close.dataset.bound = "1";
        close.addEventListener("click", hide);
      }
      function decide(decision) {
        if (!pendingApproval) return;
        var current = pendingApproval;
        post({ op: "decide", approval_id: current.approval.id, decision: decision }).then(function (data) {
          paintAudit((data && data.audit) || []);
          if (decision === "approve" && data.ok && current.retry) current.retry(current.approval.id);
          if (decision === "decline") hide();
        });
      }
      if (yes && !yes.dataset.bound) {
        yes.dataset.bound = "1";
        yes.addEventListener("click", function () { decide("approve"); });
      }
      if (no && !no.dataset.bound) {
        no.dataset.bound = "1";
        no.addEventListener("click", function () { decide("decline"); });
      }
    }
    if (!flags().paywall) return;
    var usage = $("usageOpen");
    if (usage) usage.hidden = false;
    if (usage && !usage.dataset.bound) {
      usage.dataset.bound = "1";
      usage.addEventListener("click", function () {
        post({ op: "usage" }).then(function (data) {
          if (!data.ok) return;
          paintUsage(data);
          show("usagePage");
        });
      });
    }
    [["paywallClose", hide], ["usageClose", hide]].forEach(function (pair) {
      var button = $(pair[0]);
      if (button && !button.dataset.bound) {
        button.dataset.bound = "1";
        button.addEventListener("click", pair[1]);
      }
    });
    function openPortal() {
      var note = $("paywallNote");
      post({ op: "billing-portal" }).then(function (data) {
        if (data.url) {
          window.location.href = data.url;
          return;
        }
        if (note) note.textContent = data.error || "The billing portal could not open.";
      });
    }
    var buy = $("paywallBuy");
    if (buy && !buy.dataset.bound) {
      buy.dataset.bound = "1";
      buy.addEventListener("click", function () {
        var note = $("paywallNote");
        post({ op: "checkout" }).then(function (data) {
          var provider = billingProvider(data);
          var host = provider === "square" ? "Square" : "Stripe";
          if (data.url) {
            if (note) note.textContent = "Checkout is ready. Opening " + host + " does not charge you until you pay there.";
            window.location.href = data.url;
            return;
          }
          if (note) note.textContent = data.error || (host + " is not connected yet. Nothing was charged.");
        });
      });
    }
    ["paywallPortal", "usagePortal"].forEach(function (id) {
      var button = $(id);
      if (button && !button.dataset.bound) {
        button.dataset.bound = "1";
        button.addEventListener("click", openPortal);
      }
    });
    var trial = $("paywallTrial");
    if (trial && !trial.dataset.bound) {
      trial.dataset.bound = "1";
      trial.addEventListener("click", function () {
        post({ op: "start-trial" }).then(function (data) {
          var note = $("paywallNote");
          if (!data.ok) {
            if (note) note.textContent = data.error || "The trial could not start.";
            return;
          }
          if (note) note.textContent = "Free trial started. Nothing was charged.";
        });
      });
    }
    var box = $("everyday");
    if (box && !box.dataset.paywallBound) {
      box.dataset.paywallBound = "1";
      box.addEventListener("focus", function () {
        if (!signedIn()) {
          box.blur();
          var sign = $("accountSignIn");
          if (sign) sign.click();
        }
      });
    }
    var go = $("go");
    if (go && !go.dataset.paywallBound) {
      go.dataset.paywallBound = "1";
      go.addEventListener("click", function (event) {
        if (signedIn()) return;
        event.preventDefault();
        event.stopPropagation();
        var sign = $("accountSignIn");
        if (sign) sign.click();
      }, true);
    }
  }
  window.simcoPlatform = { boot: boot, showPaywall: showPaywall, showApproval: showApproval, showSources: showSources };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
