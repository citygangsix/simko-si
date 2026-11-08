/* Simko SI voice mode. Shared by the host web UI and the Android/iOS apps.
   The host computer talks to xAI; this file never sees an API key.
   - Voice picker: Simko SI sea-life names from GET /api/voice/voices, preview per voice.
   - Mic: records, POST /api/voice/transcribe, then sends the words through the same
     composer/onSend path as typing (chat, coding plan, RUN, "fix it").
   - Replies to voice turns stream back from GET /api/voice/speak as MP3. */
(function () {
  var VOICE_KEY = "simcoVoice";
  var SPEED_KEY = "simcoVoiceSpeed";
  var state = {
    voices: [], ready: false, voice: "coral", speed: 1.0, min: 0.7, max: 1.5,
    recorder: null, stream: null, chunks: [], session: false, pendingTurn: false,
    player: null, previewing: "", silenceTimer: null, audioCtx: null
  };
  var SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";

  function $(id) { return document.getElementById(id); }
  function apiUrl(path) {
    return (window.simcoHost && window.simcoHost.rewrite) ? window.simcoHost.rewrite(path) : path;
  }
  function load(key, fallback) {
    try { var v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
  }
  function save(key, value) { try { localStorage.setItem(key, String(value)); } catch (e) {} }
  function player() {
    if (!state.player) {
      state.player = new Audio();
      state.player.preload = "auto";
      state.player.setAttribute("playsinline", "");
      state.player.addEventListener("ended", function () { setMic(state.recorder ? "listening" : "idle"); markPreview(""); });
      state.player.addEventListener("error", function () { setMic("idle"); markPreview(""); });
    }
    return state.player;
  }
  function unlock() {
    // iOS and Android only allow sound that starts from a tap, so prime the player now.
    var p = player();
    if (p.src) return;
    p.src = SILENT;
    p.play().catch(function () {});
  }
  function speakUrl(params) {
    var q = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return apiUrl("/api/voice/speak?" + q);
  }
  function play(url) {
    var p = player();
    p.pause();
    p.src = url;            // the host streams MP3 as xAI makes it, so sound starts on the first chunk
    p.playbackRate = 1.0;   // speed is applied by xAI, not by stretching audio here
    return p.play();
  }
  function stopSpeaking() {
    var p = state.player;
    if (p && !p.paused) { p.pause(); }
    markPreview("");
  }
  function trimForSpeech(text) {
    var t = String(text || "").replace(/```[\s\S]*?```/g, " (code is on screen) ").replace(/\s+/g, " ").trim();
    return t.length > 1200 ? t.slice(0, 1200) : t;
  }

  function setMic(mode) {
    var b = $("micButton");
    if (!b) return;
    b.dataset.state = mode;
    var labels = {
      idle: ["Talk to Simko SI", "🎙"],
      listening: ["Listening. Tap to send", "■"],
      thinking: ["Working on it", "…"],
      speaking: ["Speaking. Tap to stop", "🔊"],
      off: ["Voice needs Grok on the computer", "🎙"]
    };
    var l = labels[mode] || labels.idle;
    b.setAttribute("aria-label", l[0]);
    b.title = l[0];
    b.querySelector(".micGlyph").textContent = l[1];
    var hint = $("micHint");
    if (hint) {
      hint.hidden = mode === "idle" || mode === "off";
      hint.textContent = mode === "listening" ? "Listening… tap ■ when you're done"
        : mode === "thinking" ? "Got it. Working on it…"
        : mode === "speaking" ? (currentName() + " is speaking. Tap 🔊 to stop") : "";
    }
  }
  function currentName() {
    for (var i = 0; i < state.voices.length; i++) if (state.voices[i].id === state.voice) return state.voices[i].name;
    return "Coral";
  }

  async function startListening() {
    unlock();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
      say("This screen can't use the microphone. Open Simko SI in the app or on the computer itself.", true);
      return;
    }
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      setReply("Simko SI needs microphone access for voice. Allow it in Settings and tap the mic again.");
      setMic("idle");
      return;
    }
    var types = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"];
    var mime = "";
    for (var i = 0; i < types.length; i++) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) { mime = types[i]; break; }
    }
    state.chunks = [];
    state.recorder = mime ? new MediaRecorder(state.stream, { mimeType: mime }) : new MediaRecorder(state.stream);
    state.recorder.ondataavailable = function (ev) { if (ev.data && ev.data.size) state.chunks.push(ev.data); };
    state.recorder.onstop = finishListening;
    state.recorder.start(250);
    stopSpeaking();
    setMic("listening");
    watchSilence(state.stream);
    setTimeout(function () { if (state.recorder && state.recorder.state === "recording") state.recorder.stop(); }, 60000);
  }

  function watchSilence(stream) {
    // Send automatically after ~1.2 s of quiet once you have spoken, like a phone call.
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      state.audioCtx = state.audioCtx || new Ctx();
      var src = state.audioCtx.createMediaStreamSource(stream);
      var an = state.audioCtx.createAnalyser();
      an.fftSize = 1024;
      src.connect(an);
      var buf = new Uint8Array(an.fftSize);
      var heard = false, quietSince = 0;
      var tick = function () {
        if (!state.recorder || state.recorder.state !== "recording") return;
        an.getByteTimeDomainData(buf);
        var peak = 0;
        for (var i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128));
        var now = Date.now();
        if (peak > 14) { heard = true; quietSince = 0; }
        else if (heard) {
          quietSince = quietSince || now;
          if (now - quietSince > 1200) { state.recorder.stop(); return; }
        }
        state.silenceTimer = requestAnimationFrame(tick);
      };
      tick();
    } catch (e) {}
  }

  async function finishListening() {
    var rec = state.recorder;
    state.recorder = null;
    if (state.stream) state.stream.getTracks().forEach(function (t) { t.stop(); });
    state.stream = null;
    var type = (rec && rec.mimeType) || "audio/webm";
    var blob = new Blob(state.chunks, { type: type });
    state.chunks = [];
    if (!blob.size) { setMic("idle"); return; }
    setMic("thinking");
    var audio = await new Promise(function (resolve) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result || "").split(",")[1] || ""); };
      r.onerror = function () { resolve(""); };
      r.readAsDataURL(blob);
    });
    var data = null;
    try {
      var res = await fetch("/api/voice/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio: audio, mime: type.split(";")[0] })
      });
      data = await res.json();
    } catch (e) { data = null; }
    if (!data || !data.ok || !data.text) {
      setMic("idle");
      say((data && data.everyday) || "I didn't catch that. Try the mic again.", true);
      return;
    }
    // Same path as typing: the words go into the box and the normal Send runs.
    state.session = true;
    state.pendingTurn = true;
    var box = $("everyday");
    box.value = data.text;
    $("composer").requestSubmit();
  }

  function setReply(text) { var r = $("reply-bubble"); if (r) r.textContent = text; }

  function say(text, force) {
    if (!force && !state.session) return;
    var line = trimForSpeech(text);
    if (!line) { setMic("idle"); return; }
    setMic("speaking");
    play(speakUrl({ voice: state.voice, speed: state.speed.toFixed(2), text: line })).catch(function () { setMic("idle"); });
  }

  function micTap() {
    var b = $("micButton");
    var mode = b ? b.dataset.state : "idle";
    if (mode === "off") { setReply("Voice needs Grok set up on the computer Simko SI runs from."); return; }
    if (mode === "listening") { if (state.recorder) state.recorder.stop(); return; }
    if (mode === "speaking") { stopSpeaking(); setMic("idle"); return; }
    if (mode === "thinking") return;
    startListening();
  }

  function markPreview(id) {
    state.previewing = id;
    var list = $("voiceList");
    if (!list) return;
    list.querySelectorAll("button.voicePlay").forEach(function (b) {
      var on = b.dataset.voice === id;
      b.textContent = on ? "■" : "▶";
      b.setAttribute("aria-label", (on ? "Stop " : "Play ") + b.dataset.name);
    });
  }

  function preview(id, name) {
    unlock();
    if (state.previewing === id) { stopSpeaking(); return; }
    markPreview(id);
    play(speakUrl({ voice: id, speed: state.speed.toFixed(2), preview: 1 })).catch(function () { markPreview(""); });
  }

  function choose(id) {
    state.voice = id;
    save(VOICE_KEY, id);
    var list = $("voiceList");
    if (list) list.querySelectorAll("button.voicePick").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.voice === id ? "true" : "false");
    });
    var now = $("voiceNow");
    if (now) now.textContent = currentName();
    revealPicked();
  }

  function paint() {
    var list = $("voiceList");
    if (!list) return;
    list.innerHTML = "";
    state.voices.forEach(function (v) {
      var row = document.createElement("div");
      row.className = "voiceRow";
      var pick = document.createElement("button");
      pick.type = "button";
      pick.className = "voicePick";
      pick.dataset.voice = v.id;
      pick.setAttribute("aria-pressed", v.id === state.voice ? "true" : "false");
      var nm = document.createElement("span"); nm.className = "voiceName"; nm.textContent = v.name;
      var tn = document.createElement("span"); tn.className = "voiceTone"; tn.textContent = v.tone;
      pick.appendChild(nm); pick.appendChild(tn);
      pick.addEventListener("click", function () { choose(v.id); });
      var playB = document.createElement("button");
      playB.type = "button";
      playB.className = "voicePlay";
      playB.dataset.voice = v.id;
      playB.dataset.name = v.name;
      playB.textContent = "▶";
      playB.setAttribute("aria-label", "Play " + v.name);
      playB.addEventListener("click", function () { preview(v.id, v.name); });
      row.appendChild(pick); row.appendChild(playB);
      list.appendChild(row);
    });
    choose(state.voice);
    paintSpeed();
  }

  function paintSpeed() {
    var s = $("voiceSpeed"), out = $("voiceSpeedOut");
    if (!s) return;
    s.min = state.min; s.max = state.max; s.step = 0.05; s.value = state.speed;
    if (out) out.textContent = state.speed.toFixed(2).replace(/0$/, "") + "×" + (Math.abs(state.speed - 1) < 0.001 ? " (normal)" : "");
  }

  // Keep the chosen voice visible in the scrolling list (the drawer is
  // hidden at paint time, so this also runs when the drawer opens).
  function revealPicked() {
    var list = $("voiceList");
    var picked = list && list.querySelector('button.voicePick[aria-pressed="true"]');
    if (!picked || list.scrollHeight <= list.clientHeight) return;
    var row = picked.parentNode.getBoundingClientRect();
    var box = list.getBoundingClientRect();
    if (row.top < box.top || row.bottom > box.bottom) list.scrollTop += row.top - box.top - 4;
  }

  async function boot() {
    state.voice = load(VOICE_KEY, "coral");
    state.speed = parseFloat(load(SPEED_KEY, "1")) || 1;
    var mic = $("micButton");
    if (mic) mic.addEventListener("click", micTap);
    var s = $("voiceSpeed");
    if (s) s.addEventListener("input", function () {
      state.speed = Math.min(state.max, Math.max(state.min, parseFloat(s.value) || 1));
      save(SPEED_KEY, state.speed);
      paintSpeed();
    });
    var reset = $("voiceSpeedReset");
    var tools = $("toolsToggle");
    if (tools) tools.addEventListener("click", function () { setTimeout(revealPicked, 80); });
    if (reset) reset.addEventListener("click", function () { state.speed = 1; save(SPEED_KEY, 1); paintSpeed(); });
    try {
      var res = await fetch("/api/voice/voices");
      var data = await res.json();
      if (data && Array.isArray(data.voices)) {
        state.voices = data.voices;
        state.ready = !!data.ready;
        state.min = data.min_speed || 0.7;
        state.max = data.max_speed || 1.5;
        if (!load(SPEED_KEY, "")) state.speed = data.default_speed || 1;
        if (!state.voices.some(function (v) { return v.id === state.voice; })) state.voice = data.default_voice || "coral";
      }
    } catch (e) {}
    paint();
    setMic(state.ready || !state.voices.length ? "idle" : "off");
  }

  window.simcoVoice = {
    // chat.html calls these so voice turns use the exact same send/reply code as typing.
    consumeTurn: function () { var v = state.pendingTurn; state.pendingTurn = false; if (!v) state.session = false; return v; },
    reply: function (text) {
      if (state.session) { say(text); return; }
      var b = $("micButton");
      if (b && b.dataset.state === "thinking") setMic("idle");
    },
    say: say,
    stop: stopSpeaking,
    choose: choose,
    state: state,
    boot: boot
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
