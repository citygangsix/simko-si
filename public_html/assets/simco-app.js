(function () {
  const DEMO_CHATS = [
    { id: "demo-career", title: "Career plan", messages: [
      { role: "user", text: "Help me ship the career plan." },
      { role: "assistant", text: "Career is in play." }
    ]},
    { id: "demo-health", title: "Health check", messages: [
      { role: "user", text: "I slept badly and skipped the gym." },
      { role: "assistant", text: "Health and Fitness is strained." }
    ]},
    { id: "demo-calc", title: "Calculator", messages: [
      { role: "user", text: "Make multiply show 7 times 8." },
      { role: "assistant", text: "Multiplication is in. I tested it in a browser: 7 × 8 = shows 56." }
    ]},
    { id: "demo-family", title: "Family", messages: [
      { role: "user", text: "The kids need a quieter evening." },
      { role: "assistant", text: "Parenting is in play." }
    ]},
    { id: "demo-money", title: "Money", messages: [
      { role: "user", text: "The budget is tight this month." },
      { role: "assistant", text: "Financial Life is strained." }
    ]},
    { id: "demo-friends", title: "Friends", messages: [
      { role: "user", text: "I want to see friends this weekend." },
      { role: "assistant", text: "Social Life is in play." }
    ]},
    { id: "demo-evening", title: "Quiet evening", messages: [
      { role: "user", text: "Home feels restless." },
      { role: "assistant", text: "Quality of Life is in play." }
    ]},
    { id: "demo-goal", title: "A goal", messages: [
      { role: "user", text: "My goal is a calmer year." },
      { role: "assistant", text: "Life Vision is in play." }
    ]},
    { id: "demo-learn", title: "Learning", messages: [
      { role: "user", text: "I want to read one book." },
      { role: "assistant", text: "Intellectual Life is in play." }
    ]},
    { id: "demo-love", title: "Partner", messages: [
      { role: "user", text: "Date night went well." },
      { role: "assistant", text: "Love Relationship is doing well." }
    ]}
  ];

  let authToken = "";
  let activeSessionId = "";
  let chatRows = [];
  let sessionCache = {};
  let activeRole = "coding";
  let model = "";

  function $(id) { return document.getElementById(id); }

  function voiceReply(text) {
    if (window.simcoVoice) window.simcoVoice.reply(text);
  }

  function detectIntent(text) {
    const t = text.toLowerCase();
    const has = (re) => re.test(t);
    if (has(/\b(python|javascript|typescript|node|java|rust|golang|ruby|php|bash|kotlin|swift|tkinter|flask|django|command[- ]line|cli|terminal|script|program|module|function|class|pytest|unit tests?|tests?|repo|repository|package|library)\b/)
        || has(/\b[\w-]+\.(py|js|ts|sh|rb|go|rs|java)\b/) || has(/\bwrite (a|me a) program\b/)) return "";
    if (has(/\b(division|divide|divided|divides|dividing)\b/)) return "div";
    if (has(/\bmulti-?digit\b/)) return "mul_multi";
    if (has(/\bdecimals?\b/)) return "decimal";
    if (has(/\b(subtract|subtracts|subtracting|subtraction|minus)\b/)) return "sub";
    if (has(/\b(add|adds|adding|addition|plus)\b/)) return "add";
    if (has(/\b(multiply|multiplies|multiplying|multiplication|times)\b/)) return "mul";
    if (has(/\b(calculator|front end|shell)\b/)) return "fe_shell";
    return "";
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    let data = {};
    try { data = await response.json(); } catch (e) { data = {}; }
    return data;
  }

  function authPost(body) {
    return postJson("/api/auth", body);
  }

  function sessionPost(body) {
    return postJson("/api/sessions", Object.assign({ token: authToken }, body));
  }

  function cacheSave() {
    try {
      localStorage.setItem("simko.cache.v1", JSON.stringify({
        email: $("authWho").textContent || "",
        order: chatRows.map((row) => row.id),
        sessions: sessionCache
      }));
    } catch (e) {}
  }

  function cacheLoad() {
    try { return JSON.parse(localStorage.getItem("simko.cache.v1") || "null"); }
    catch (e) { return null; }
  }

  function restoreCache() {
    const bag = cacheLoad();
    if (!bag || !bag.sessions) return false;
    const order = bag.order || Object.keys(bag.sessions);
    chatRows = order.map((id) => bag.sessions[id]).filter(Boolean).slice(0, 10);
    sessionCache = bag.sessions;
    if (!chatRows.length) return false;
    $("authWho").textContent = bag.email || "";
    paintChatList(chatRows, false);
    showSessionFromCache(chatRows[0].id, false);
    return true;
  }

  function setConnected(on) {
    const mark = $("stackMark");
    mark.textContent = on ? "●" : "○";
    mark.title = on ? "Connected on this browser" : "Not connected";
    mark.setAttribute("aria-label", mark.title);
  }

  async function autoConnect() {
    try {
      const response = await fetch("/api/health");
      const data = await response.json();
      const on = !!(data && data.ok);
      setConnected(on);
      $("installWord").textContent = on ? "Ready" : "Waiting";
    } catch (e) {
      setConnected(false);
      $("installWord").textContent = "Waiting";
    }
  }

  function openThread() {
    document.body.classList.add("thread-open");
  }

  function chatMark(title) {
    const hay = String(title || "").toLowerCase();
    const pairs = [
      ["career", "💼"], ["health", "🩺"], ["calc", "🧮"], ["family", "👨‍👩‍👧"],
      ["money", "💰"], ["friend", "🤝"], ["evening", "🌙"], ["goal", "🎯"],
      ["learn", "📚"], ["partner", "❤️"], ["love", "❤️"], ["turtle", "🐢"], ["hello", "🌊"]
    ];
    for (let i = 0; i < pairs.length; i++) {
      if (hay.indexOf(pairs[i][0]) >= 0) return pairs[i][1];
    }
    return "💬";
  }

  function setThreadTitle(title) {
    $("threadTitle").textContent = title || "Chat";
  }

  function messageText(message) {
    if (message.role === "relay") return "From " + (message.from_title || "another chat") + ": " + message.text;
    if (message.role === "relay_out") return "Sent to " + (message.to_title || "another chat") + ": " + message.text;
    return message.text;
  }

  function renderHistory(session) {
    if (session && session.title) setThreadTitle(session.title);
    const history = $("historyBubbles");
    const reply = $("reply-bubble");
    history.replaceChildren();
    const messages = (session && session.messages) || [];
    messages.forEach((message, index) => {
      const last = index === messages.length - 1;
      const mine = message.role === "user" || message.role === "relay_out";
      if (last && !mine) {
        reply.textContent = messageText(message);
        return;
      }
      const bubble = document.createElement("div");
      bubble.className = mine ? "bubble mine" : "bubble theirs";
      bubble.textContent = messageText(message);
      history.appendChild(bubble);
    });
    const tail = messages[messages.length - 1];
    if (!tail || tail.role === "user" || tail.role === "relay_out") reply.textContent = "";
  }

  function fillChatSelect(select, rows, skipId) {
    const previous = select.value;
    select.replaceChildren();
    rows.forEach((row) => {
      if (skipId && row.id === skipId) return;
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = row.title || "Chat";
      select.appendChild(option);
    });
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  }

  function paintChatList(rows, demo) {
    const list = $("sessionList");
    list.replaceChildren();
    rows.forEach((row) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.id = row.id;
      const mark = document.createElement("span");
      mark.className = "chatEmoji";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = chatMark(row.title);
      const label = document.createElement("span");
      label.textContent = row.title || "Chat";
      button.append(mark, label);
      button.setAttribute("aria-pressed", row.id === activeSessionId ? "true" : "false");
      button.addEventListener("click", () => {
        if (demo) {
          activeSessionId = row.id;
          document.querySelectorAll("#sessionList button").forEach((item) => {
            item.setAttribute("aria-pressed", item.dataset.id === row.id ? "true" : "false");
          });
          renderHistory(row);
          openThread();
          return;
        }
        showSession(row.id, true);
      });
      list.appendChild(button);
    });
  }

  function showDemoList() {
    document.body.classList.remove("thread-open");
    activeSessionId = "";
    paintChatList(DEMO_CHATS, true);
    setThreadTitle("New chat");
    $("historyBubbles").replaceChildren();
    $("reply-bubble").textContent = "";
  }

  function showMyMessage(text) {
    const history = $("historyBubbles");
    const reply = $("reply-bubble");
    if (reply.textContent.trim() && reply.textContent !== "Working on it…") {
      const prev = document.createElement("div");
      prev.className = "bubble theirs";
      prev.textContent = reply.textContent;
      history.appendChild(prev);
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble mine";
    bubble.textContent = text;
    history.appendChild(bubble);
    reply.textContent = "";
    const thread = $("thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
  }

  function showSessionFromCache(sessionId, open) {
    const session = sessionCache[sessionId];
    if (!session) return;
    activeSessionId = session.id;
    document.querySelectorAll("#sessionList button").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.id === activeSessionId ? "true" : "false");
    });
    renderHistory(session);
    fillChatSelect($("relayTarget"), chatRows, activeSessionId);
    if (open) openThread();
  }

  async function showSession(sessionId, open) {
    const data = await sessionPost({ op: "get", session_id: sessionId });
    if (!data.ok || !data.session) {
      showSessionFromCache(sessionId, open);
      return;
    }
    activeSessionId = data.session.id;
    sessionCache[data.session.id] = data.session;
    const row = chatRows.find((item) => item.id === data.session.id);
    if (row) row.title = data.session.title;
    document.querySelectorAll("#sessionList button").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.id === activeSessionId ? "true" : "false");
      if (button.dataset.id === data.session.id) {
        const label = button.querySelector("span:last-child");
        if (label) label.textContent = data.session.title || "Chat";
      }
    });
    renderHistory(data.session);
    fillChatSelect($("relayTarget"), chatRows, activeSessionId);
    cacheSave();
    if (open) openThread();
  }

  async function refreshChats(preferId) {
    const data = await sessionPost({ op: "list" });
    chatRows = (data && data.sessions) || [];
    if (!data || data.ok === false) {
      if (!restoreCache()) showDemoList();
      return;
    }
    if (!chatRows.length) {
      const created = await sessionPost({ op: "create", title: "Chat 1" });
      if (created.session) chatRows = [created.session];
    }
    chatRows.forEach((row) => {
      sessionCache[row.id] = Object.assign({}, sessionCache[row.id] || {}, row);
    });
    paintChatList(chatRows, false);
    const wanted = preferId || activeSessionId || (chatRows[0] && chatRows[0].id);
    if (wanted) await showSession(wanted, false);
    cacheSave();
  }

  function showSignedOut() {
    authToken = "";
    window.simcoUserToken = "";
    activeSessionId = "";
    chatRows = [];
    try { sessionStorage.removeItem("podcoderToken"); } catch (e) {}
    ["authEmail", "authPassword", "signUp", "signIn", "resetPassword"].forEach((id) => { $(id).hidden = false; });
    ["signOut", "confirmEmail", "authTokenBox", "setPassword"].forEach((id) => { $(id).hidden = true; });
    $("authWho").textContent = "";
    $("relay-sheet").hidden = true;
    showDemoList();
    loadLife();
  }

  function showSignedIn(email) {
    window.simcoUserToken = authToken;
    if (window.simcoThemes) window.simcoThemes.syncFromServer();
    ["authEmail", "authPassword", "signUp", "signIn", "confirmEmail", "resetPassword"].forEach((id) => { $(id).hidden = true; });
    $("signOut").hidden = false;
    $("authWho").textContent = email;
    $("drawer").hidden = true;
    $("toolsToggle").setAttribute("aria-expanded", "false");
    loadLife();
  }

  async function submitAuth(op) {
    const email = $("authEmail").value.trim();
    const password = $("authPassword").value;
    const data = await authPost({ op: op, email: email, password: password });
    if (!data.ok || !data.token) {
      $("reply-bubble").textContent = data.error || "Sign in failed.";
      openThread();
      return;
    }
    authToken = data.token;
    try { sessionStorage.setItem("podcoderToken", authToken); } catch (e) {}
    $("authPassword").value = "";
    showSignedIn(data.email || email);
    if (data.dev_token) {
      $("authTokenBox").value = data.dev_token;
      $("authTokenBox").hidden = false;
      $("confirmEmail").hidden = false;
      $("drawer").hidden = false;
      $("toolsToggle").setAttribute("aria-expanded", "true");
    }
    await refreshChats();
  }

  async function confirmEmail() {
    const data = await authPost({ op: "confirm-email", confirm_token: $("authTokenBox").value.trim(), token: authToken });
    $("reply-bubble").textContent = data.ok ? "Email confirmed." : (data.error || "Confirm failed.");
    openThread();
  }

  async function resetPassword() {
    const data = await authPost({ op: "request-reset", email: $("authEmail").value.trim() });
    if (!data.ok) {
      $("reply-bubble").textContent = data.error || "Reset failed.";
      openThread();
      return;
    }
    if (data.dev_token) {
      $("authTokenBox").value = data.dev_token;
      $("authTokenBox").hidden = false;
      $("setPassword").hidden = false;
      $("reply-bubble").textContent = "No mail server. The reset token is on screen. Type a new password, then Set password.";
      openThread();
      return;
    }
    $("reply-bubble").textContent = "If that email is registered, a reset note was sent.";
    openThread();
  }

  async function setPassword() {
    const data = await authPost({
      op: "reset-password",
      reset_token: $("authTokenBox").value.trim(),
      password: $("authPassword").value
    });
    $("reply-bubble").textContent = data.ok ? "Password updated. Sign in with the new one." : (data.error || "Reset failed.");
    if (data.ok) {
      $("authPassword").value = "";
      $("authTokenBox").value = "";
      $("setPassword").hidden = true;
    }
    openThread();
  }

  async function signOut() {
    if (authToken) await authPost({ op: "signout", token: authToken });
    showSignedOut();
    $("reply-bubble").textContent = "";
  }

  async function newChat() {
    if (!authToken) {
      $("drawer").hidden = false;
      $("toolsToggle").setAttribute("aria-expanded", "true");
      $("reply-bubble").textContent = "Sign in to open a chat.";
      openThread();
      return;
    }
    const created = await sessionPost({ op: "create", title: "Chat " + (chatRows.length + 1) });
    if (!created.ok && !created.session) {
      $("reply-bubble").textContent = created.error || "Could not open a chat.";
      return;
    }
    await refreshChats(created.session.id);
    openThread();
  }

  async function rememberTurn(userText, assistantText) {
    if (!authToken) return;
    if (!activeSessionId || String(activeSessionId).indexOf("demo-") === 0) {
      const created = await sessionPost({ op: "create", title: "Chat " + (chatRows.length + 1) });
      if (created.session) {
        activeSessionId = created.session.id;
        chatRows.unshift(created.session);
      }
    }
    await sessionPost({ op: "append", session_id: activeSessionId, role: "user", text: userText });
    await sessionPost({ op: "append", session_id: activeSessionId, role: "assistant", text: assistantText });
    await showSession(activeSessionId, false);
  }

  async function onSend(event) {
    if (event) event.preventDefault();
    const text = $("everyday").value.trim();
    if (!text) return;
    if (window.simcoVoice) window.simcoVoice.consumeTurn();
    if (!authToken) {
      $("drawer").hidden = false;
      $("toolsToggle").setAttribute("aria-expanded", "true");
      $("reply-bubble").textContent = "Sign in to talk with Simko SI.";
      openThread();
      return;
    }
    const reply = $("reply-bubble");
    showMyMessage(text);
    $("everyday").value = "";
    reply.textContent = "Working on it…";
    let everyday = "";
    try {
      const data = await postJson("/api/simco/turn", {
        text: text,
        token: authToken,
        session_id: activeSessionId || "",
        feature: detectIntent(text)
      });
      everyday = (data && (data.everyday || data.error)) || "";
      if (data && data.model) model = data.model;
    } catch (e) {
      everyday = "Simko SI could not be reached. Try again in a moment.";
    }
    const line = everyday || "No reply came back from Simko SI. Try again in a moment.";
    reply.textContent = line;
    voiceReply(line);
    await rememberTurn(text, line);
    await tagTurn(text);
  }

  async function sendToOtherChat() {
    const text = $("everyday").value.trim();
    const target = $("relayTarget").value;
    if (!text) {
      $("reply-bubble").textContent = "Type a message, then Send to chat.";
      openThread();
      return;
    }
    if (!target) {
      $("reply-bubble").textContent = "Open another chat first.";
      openThread();
      return;
    }
    const data = await sessionPost({
      op: "relay",
      from_session_id: activeSessionId,
      to_session_id: target,
      text: text
    });
    $("relay-sheet").hidden = true;
    if (!data.ok) {
      $("reply-bubble").textContent = data.error || "Could not send to that chat.";
      openThread();
      return;
    }
    $("everyday").value = "";
    await showSession(activeSessionId, true);
  }

  async function searchChats() {
    const q = $("chatSearch").value.trim();
    if (!authToken) {
      const rows = DEMO_CHATS.filter((row) => {
        if (!q) return true;
        const blob = (row.title + " " + (row.messages || []).map((message) => message.text).join(" ")).toLowerCase();
        return blob.indexOf(q.toLowerCase()) >= 0;
      });
      paintChatList(rows, true);
      return;
    }
    try {
      const data = await sessionPost({ op: "search", q: q });
      chatRows = (data && data.sessions) || [];
      paintChatList(chatRows, false);
    } catch (e) {
      $("reply-bubble").textContent = "Search could not reach Simko SI.";
    }
  }

  function paintLife(data) {
    const box = $("lifeTags");
    const last = $("lifeLast");
    const rows = (data && data.categories) || [];
    const tags = (data && data.tags) || [];
    const current = tags.length ? tags[tags.length - 1].category : "";
    box.replaceChildren();
    rows.forEach((row) => {
      const button = document.createElement("button");
      button.type = "button";
      const words = (data && data.statuses) || {};
      button.textContent = row.label + " · " + (words[row.id] || "not discussed");
      button.setAttribute("aria-pressed", row.id === current ? "true" : "false");
      button.addEventListener("click", () => retag(row.id));
      box.appendChild(button);
    });
    const tagged = tags.length ? "Tagged as " + tags[tags.length - 1].label + "." : "Words only. No grade.";
    last.textContent = data && data.dominance_note ? data.dominance_note + " " + tagged : tagged;
    const counts = $("lifeCountBody");
    if (counts) {
      const rowsN = (data && data.counts) || [];
      counts.textContent = rowsN.length
        ? rowsN.map((row) => row.label + ": " + row.n).join("\n")
        : "No counts yet.";
    }
  }

  async function loadLife() {
    try {
      const data = await postJson("/api/memory", { op: "list", token: authToken });
      paintLife(data);
    } catch (e) {
      paintLife(null);
    }
  }

  async function tagTurn(text) {
    if (!authToken) return;
    const data = await postJson("/api/memory", { op: "tag", token: authToken, text: text, session_id: activeSessionId });
    if (data && data.tagged) paintLife(data);
  }

  async function retag(category) {
    if (!authToken) {
      $("lifeLast").textContent = "Sign in to tag a line.";
      return;
    }
    const data = await postJson("/api/memory", { op: "retag", token: authToken, category: category });
    if (!data.ok) {
      $("lifeLast").textContent = data.error || "Nothing to tag.";
      return;
    }
    paintLife(data);
  }

  function setRole(role) {
    activeRole = role;
    $("roleCoding").setAttribute("aria-pressed", role === "coding" ? "true" : "false");
    $("roleVideo").setAttribute("aria-pressed", role === "video" ? "true" : "false");
    $("roleImage").setAttribute("aria-pressed", role === "image" ? "true" : "false");
    const gallery = $("gallery");
    if (!gallery) return;
    const show = role === "video" || role === "image";
    gallery.hidden = !show;
    const clip = gallery.querySelector("video");
    if (!clip) return;
    if (show) clip.play().catch(function () {});
    else clip.pause();
  }

  async function probeMachine() {
    const cores = navigator.hardwareConcurrency || 0;
    const ram = navigator.deviceMemory || 0;
    const ua = navigator.userAgent || "";
    let os = "this browser";
    if (/Android/i.test(ua)) os = "Android";
    else if (/iPhone|iPad|iPod/i.test(ua)) os = "iPhone or iPad";
    else if (/Mac OS X/i.test(ua)) os = "Mac";
    else if (/Windows/i.test(ua)) os = "Windows";
    else if (/Linux/i.test(ua)) os = "Linux";
    let gpu = "";
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (gl) {
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        gpu = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "") : String(gl.getParameter(gl.RENDERER) || "");
      }
    } catch (e) {}
    let webgpu = "";
    try {
      if (navigator.gpu && navigator.gpu.requestAdapter) {
        const adapter = await navigator.gpu.requestAdapter();
        if (adapter) {
          const info = adapter.info || {};
          webgpu = adapter.name || info.description || info.vendor || "WebGPU adapter";
        }
      }
    } catch (e) {}
    const software = /swiftshader|llvmpipe|softpipe|software|microsoft basic/i.test(gpu);
    const stack = (gpu && !software)
      ? "Recommended stack: the desktop app on this computer for a local model, and this website for Grok."
      : "Recommended stack: this website, with Grok. A desktop app can use a GPU machine later.";
    return [
      "This browser is on " + os + ".",
      cores ? (cores + " CPU cores.") : "",
      ram ? ("Memory hint " + ram + " GB.") : "Memory hint is hidden by this browser.",
      gpu ? ("GPU " + gpu + ".") : "GPU could not be read.",
      webgpu ? ("WebGPU " + webgpu + ".") : "",
      stack
    ].filter(Boolean).join(" ");
  }

  async function detectHardware() {
    const line = await probeMachine();
    $("reply-bubble").textContent = line;
    $("turtleLog").textContent = line;
    $("turtleLead").textContent = "This is the browser on this computer. Nothing was installed.";
    $("turtleStage").textContent = "Ready";
    openThread();
  }

  async function downloadNow() {
    let data = {};
    try {
      const response = await fetch("/api/installers");
      data = await response.json();
    } catch (e) {}
    const links = (data && data.installers) || [];
    if (!links.length) {
      $("reply-bubble").textContent = "Desktop app download coming soon.";
      $("installWord").textContent = "Coming soon";
      openThread();
      return;
    }
    $("reply-bubble").textContent = links.map((link) => link.label + " " + link.url).join("\n");
    openThread();
  }

  function openRent() {
    $("drawer").hidden = false;
    $("toolsToggle").setAttribute("aria-expanded", "true");
    $("rent-sheet").hidden = false;
    $("advancedNote").hidden = false;
    $("autoOffer").textContent = "Renting would reserve a separate GPU computer so a local model can run there. Nothing is ordered from this website. Confirm Rent stays off until you are in the desktop app.";
  }

  function confirmRent() {
    $("reply-bubble").textContent = "Confirm Rent is turned off on the website. It needs the desktop app. This site does not call a rental service.";
    openThread();
  }

  function showTurtle() {
    $("turtleScreen").hidden = false;
  }

  function hideTurtle(remember) {
    $("turtleScreen").hidden = true;
    if (remember) {
      try { sessionStorage.setItem("simcoTurtleSeen", "1"); } catch (e) {}
    }
  }

  async function bootAuth() {
    try { authToken = sessionStorage.getItem("podcoderToken") || ""; } catch (e) { authToken = ""; }
    try {
      const data = await authPost({ op: "me", token: authToken });
      if (!data.ok) {
        showSignedOut();
        return;
      }
      showSignedIn(data.email);
      await refreshChats();
    } catch (e) {
      if (!authToken || !restoreCache()) showSignedOut();
    }
  }

  function applyFold() {
    let segmented = false;
    try {
      segmented = window.matchMedia("(horizontal-viewport-segments: 2), (vertical-viewport-segments: 2)").matches;
    } catch (err) {
      segmented = false;
    }
    const cover = window.matchMedia("(max-width: 640px), (max-height: 560px)").matches;
    document.body.classList.toggle("narrow", !segmented && cover);
  }

  function bindFold() {
    applyFold();
    ["(max-width: 640px), (max-height: 560px)", "(horizontal-viewport-segments: 2), (vertical-viewport-segments: 2)"].forEach((query) => {
      try { window.matchMedia(query).addEventListener("change", applyFold); } catch (err) {}
    });
  }

  function armTurtleMotion() {
    function markHidden() {
      document.documentElement.classList.toggle("simco-turtle-paused", document.hidden);
    }
    document.addEventListener("visibilitychange", markHidden);
    let idleTimer = 0;
    function bump() {
      document.documentElement.classList.remove("simco-turtle-idle");
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => document.documentElement.classList.add("simco-turtle-idle"), 20000);
    }
    ["pointermove", "keydown", "touchstart"].forEach((name) => {
      window.addEventListener(name, bump, { passive: true });
    });
    markHidden();
    bump();
  }

  $("composer").addEventListener("submit", onSend);
  $("everyday").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("signUp").addEventListener("click", () => submitAuth("signup"));
  $("signIn").addEventListener("click", () => submitAuth("signin"));
  $("confirmEmail").addEventListener("click", confirmEmail);
  $("resetPassword").addEventListener("click", resetPassword);
  $("setPassword").addEventListener("click", setPassword);
  $("signOut").addEventListener("click", signOut);
  $("toolsToggle").addEventListener("click", () => {
    const drawer = $("drawer");
    drawer.hidden = !drawer.hidden;
    $("toolsToggle").setAttribute("aria-expanded", drawer.hidden ? "false" : "true");
  });
  $("newChat").addEventListener("click", newChat);
  $("searchChats").addEventListener("click", () => {
    $("chatSearch").hidden = false;
    $("chatSearch").focus();
  });
  $("chatSearch").addEventListener("input", () => searchChats());
  $("sendToChat").addEventListener("click", async () => {
    if (!authToken) {
      $("drawer").hidden = false;
      $("reply-bubble").textContent = "Sign in to send to another chat.";
      openThread();
      return;
    }
    await refreshChats(activeSessionId);
    $("drawer").hidden = false;
    $("toolsToggle").setAttribute("aria-expanded", "true");
    $("relay-sheet").hidden = false;
    fillChatSelect($("relayTarget"), chatRows, activeSessionId);
  });
  $("relayGo").addEventListener("click", sendToOtherChat);
  $("backToList").addEventListener("click", () => document.body.classList.remove("thread-open"));
  $("roleCoding").addEventListener("click", () => setRole("coding"));
  $("roleVideo").addEventListener("click", () => setRole("video"));
  $("roleImage").addEventListener("click", () => setRole("image"));
  $("detectHardware").addEventListener("click", detectHardware);
  $("downloadNow").addEventListener("click", downloadNow);
  $("whatRent").addEventListener("click", openRent);
  $("confirmRentGo").addEventListener("click", confirmRent);
  $("advancedLink").addEventListener("click", (event) => {
    event.preventDefault();
    $("drawer").hidden = false;
    $("toolsToggle").setAttribute("aria-expanded", "true");
    $("advancedNote").hidden = false;
    $("rent-sheet").hidden = false;
    openRent();
  });
  $("turtleEnter").addEventListener("click", () => hideTurtle(true));
  $("turtlePeek").addEventListener("click", () => hideTurtle(false));
  $("openTurtle").addEventListener("click", () => showTurtle());
  $("openHost").addEventListener("click", () => {
    $("hostRow").hidden = false;
    $("hostHint").textContent = "This website talks to Grok here. The phone app can point at a computer. That redirect is off on the website.";
    showTurtle();
  });
  $("hostSave").addEventListener("click", () => {
    $("hostHint").textContent = "Left on this website. Chats stay with your account and Grok answers them here.";
  });
  $("turtleRedetect").addEventListener("click", () => detectHardware().then(() => showTurtle()));
  $("turtleCheck").addEventListener("click", () => {
    $("turtleStage").textContent = "Waiting";
    $("turtleLead").textContent = "This website does not install a local model. The desktop app does that on the computer.";
    $("turtleError").hidden = false;
    $("turtleError").textContent = "Desktop app download coming soon.";
  });
  $("turtleAsk").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("turtleQuestion").value.trim();
    if (!text) {
      $("turtleError").hidden = false;
      $("turtleError").textContent = "Type a question, then Send.";
      return;
    }
    if (!authToken) {
      $("turtleError").hidden = false;
      $("turtleError").textContent = "Sign in to ask Simko SI.";
      return;
    }
    $("turtleError").hidden = true;
    $("turtleReply").textContent = "Working on it…";
    $("everyday").value = text;
    await onSend();
    $("turtleReply").textContent = $("reply-bubble").textContent;
    $("turtleQuestion").value = "";
  });

  bindFold();
  armTurtleMotion();
  showDemoList();
  autoConnect();
  bootAuth();
})();
