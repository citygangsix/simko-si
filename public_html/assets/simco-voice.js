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
    player: null, previewing: "", silenceTimer: null, audioCtx: null,
    live: false, liveGen: 0, livePhase: "off", micPaused: false, muted: false, playbackGen: 0
  };
  var lastSpoken = "";
  var fallbackUsed = false;
  var SEA = [
    {id:"coral",name:"Coral",tone:"Soft and soothing"},
    {id:"kelp",name:"Kelp",tone:"Gentle and patient"},
    {id:"manta",name:"Manta",tone:"Rich and cinematic"},
    {id:"nautilus",name:"Nautilus",tone:"Elegant and refined"},
    {id:"dolphin",name:"Dolphin",tone:"Friendly and upbeat"},
    {id:"orca",name:"Orca",tone:"Powerful and dramatic"},
    {id:"turtle",name:"Turtle",tone:"Calm and wise"},
    {id:"seahorse",name:"Seahorse",tone:"Playful and quick"},
    {id:"starfish",name:"Starfish",tone:"Bright and energetic"},
    {id:"anemone",name:"Anemone",tone:"Reassuring and warm"},
    {id:"urchin",name:"Urchin",tone:"Sharp and focused"},
    {id:"octopus",name:"Octopus",tone:"Inventive and curious"},
    {id:"squid",name:"Squid",tone:"Precise and steady"},
    {id:"jellyfish",name:"Jellyfish",tone:"Serene and radiant"},
    {id:"manatee",name:"Manatee",tone:"Warm and steadfast"},
    {id:"walrus",name:"Walrus",tone:"Strong and low"},
    {id:"seal",name:"Seal",tone:"Smooth and balanced"},
    {id:"otter",name:"Otter",tone:"Easygoing and kind"},
    {id:"marlin",name:"Marlin",tone:"Bold and dynamic"},
    {id:"ray",name:"Ray",tone:"Warm and articulate"},
    {id:"crab",name:"Crab",tone:"Clear and confident"},
    {id:"lobster",name:"Lobster",tone:"Confident and trustworthy"},
    {id:"shrimp",name:"Shrimp",tone:"Bright and curious"},
    {id:"clownfish",name:"Clownfish",tone:"Energetic and upbeat"},
    {id:"angelfish",name:"Angelfish",tone:"Warm and friendly"},
    {id:"puffer",name:"Puffer",tone:"Thoughtful and wise"},
    {id:"eel",name:"Eel",tone:"Commanding and calm"},
    {id:"whale",name:"Whale",tone:"Grounded and luminous"}
  ];
  function fallbackSpeak(text) {
    if (state.muted) { resumeLiveAfterSpeech(); return; }
    if (!text || !window.speechSynthesis) { voiceNote("Speech playback is unavailable. You can read the reply below."); setMic("idle"); markPreview(""); resumeLiveAfterSpeech(); return; }
    var playbackGen = state.playbackGen;
    var u = new SpeechSynthesisUtterance(text);
    u.rate = Math.min(1.5, Math.max(0.7, state.speed || 1));
    var voices = window.speechSynthesis.getVoices() || [];
    if (voices.length) {
      voiceNote("The selected Grok voice is unavailable. Using a device voice instead.");
      var idx = 0;
      for (var i = 0; i < state.voices.length; i++) if (state.voices[i].id === state.voice) idx = i;
      u.voice = voices[idx % voices.length];
    }
    u.onend = function () { if (playbackGen !== state.playbackGen) return; setMic(state.recorder ? "listening" : "idle"); markPreview(""); resumeLiveAfterSpeech(); };
    u.onerror = function () { if (playbackGen !== state.playbackGen) return; voiceNote("Speech playback failed. You can read the reply below; the mic is ready again."); setMic("idle"); markPreview(""); resumeLiveAfterSpeech(); };
    window.speechSynthesis.cancel();
    setMic("speaking");
    try { window.speechSynthesis.speak(u); } catch (e) { u.onerror(); }
  }
  function useFallback(message) {
    if (fallbackUsed || state.muted || (!state.live && !state.session && !state.previewing)) return;
    traceVoice("tts_fallback", "unknown");
    state.playbackActive = false;
    if (state.player) state.player.pause();
    voiceNote((message || "Voice audio could not play.") + " Trying the browser voice.");
    fallbackUsed = true;
    if (lastSpoken) fallbackSpeak(lastSpoken);
    else { setMic("idle"); markPreview(""); }
  }
  var SILENT = "data:audio/wav;base64,UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YSADAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==";

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
      state.player.addEventListener("ended", function () {
        if (!state.playbackActive) return;
        state.playbackActive = false; releaseSpeechUrl();
        setMic(state.recorder ? "listening" : "idle"); markPreview(""); resumeLiveAfterSpeech();
      });
      state.player.addEventListener("error", function () { if (state.playbackActive) useFallback(); });
    }
    return state.player;
  }
  function traceVoice(stage, error, status) {
    // Temporary diagnostic proposal: enums only. No transcript, audio, text,
    // cookies, session tokens, email, URL, or arbitrary exception message.
    if ((state.traceCount || 0) >= 60) return;
    state.traceCount = (state.traceCount || 0) + 1;
    var errors = ["NotAllowedError", "SecurityError", "NotFoundError", "NotReadableError", "AbortError", "TypeError", "InvalidStateError", "NotSupportedError", "no-speech", "network", "empty", "unknown"];
    var code = !error ? "" : errors.indexOf(error) >= 0 ? error : "unknown";
    fetch(apiUrl("/api/voice/clientlog"), voiceRequest({
      method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
      body: JSON.stringify({ stage: stage, error: code, status: Number(status) || 0, version: "voice-v4" })
    })).catch(function () {});
  }
  function voiceRequest(options) {
    options = options || {};
    var headers = Object.assign({}, options.headers || {});
    // Same application session used by typed chat; never put this token in a URL.
    try { var token = sessionStorage.getItem("podcoderToken"); if (token) headers.Authorization = "Bearer " + token; } catch (e) {}
    return Object.assign({}, options, { credentials: "same-origin", headers: headers });
  }
  function releaseSpeechUrl() {
    if (state.speechUrl) { URL.revokeObjectURL(state.speechUrl); state.speechUrl = null; }
  }
  function unlock() {
    // Both creation/resume and the first play MUST happen synchronously in the tap.
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) {
        state.audioCtx = state.audioCtx || new Ctx();
        if (state.audioCtx.state === "suspended") state.audioCtx.resume().catch(function () {});
      }
    } catch (e) {}
    var p = player();
    if (state.audioPrimed) return;
    p.src = SILENT; // A real 50 ms PCM recording, not the old zero-frame WAV.
    var gen = state.playbackGen;
    p.play().then(function () { if (gen === state.playbackGen) state.audioPrimed = true; }).catch(function () { if (gen === state.playbackGen) state.audioPrimed = false; });
  }
  function speakUrl(params) {
    var q = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return apiUrl("/api/voice/speak?" + q);
  }
  async function play(url) {
    if (state.muted) { resumeLiveAfterSpeech(); return; }
    var p = player();
    var previewing = state.previewing;
    stopSpeaking();
    if (previewing) markPreview(previewing);
    var gen = state.playbackGen;
    fallbackUsed = false;
    var controller = new AbortController();
    state.ttsAbort = controller;
    var timeout = setTimeout(function () { controller.abort(); }, 50000);
    try {
      traceVoice("tts_fetch");
      var response = await fetch(url, voiceRequest({ signal: controller.signal }));
      if (!response.ok) {
        traceVoice("tts_http_error", "", response.status);
        var error = await response.json().catch(function () { return {}; });
        throw new Error((error.everyday || error.error || "Voice request failed") + " (HTTP " + response.status + ").");
      }
      if (!/^audio\//i.test(response.headers.get("Content-Type") || "")) throw new Error("The voice service did not return audio.");
      var blob = await response.blob();
      traceVoice("tts_audio_ready", blob.size ? "" : "empty", response.status);
      if (!blob.size) throw new Error("The voice service returned empty audio.");
      if (gen !== state.playbackGen || state.muted) return;
      state.speechUrl = URL.createObjectURL(blob);
      p.src = state.speechUrl;
      p.playbackRate = 1;
      state.playbackActive = true;
      try { await p.play(); traceVoice("tts_element_started"); }
      catch (error) {
        if (gen !== state.playbackGen || state.muted) return;
        // Mobile autoplay policies can still block the media element. Reuse the
        // AudioContext created in the mic tap, NOT one created after this await.
        if (error.name !== "NotAllowedError" || !state.audioCtx || state.audioCtx.state !== "running") throw error;
        state.playbackActive = false;
        var decoded = await state.audioCtx.decodeAudioData(await blob.arrayBuffer());
        if (gen !== state.playbackGen || state.muted) return;
        var source = state.audioCtx.createBufferSource();
        source.buffer = decoded; source.connect(state.audioCtx.destination);
        state.speechSource = source;
        source.onended = function () {
          if (gen !== state.playbackGen) return;
          state.speechSource = null; releaseSpeechUrl();
          setMic(state.recorder ? "listening" : "idle"); markPreview(""); resumeLiveAfterSpeech();
        };
        source.start();
        traceVoice("tts_webaudio_started");
      }
    } catch (error) {
      if (gen === state.playbackGen && !state.muted) useFallback(error.message || "Voice playback failed.");
    } finally {
      clearTimeout(timeout);
      if (state.ttsAbort === controller) state.ttsAbort = null;
    }
  }
  function stopSpeaking(reset) {
    state.playbackGen += 1;
    state.playbackActive = false;
    if (state.ttsAbort) { state.ttsAbort.abort(); state.ttsAbort = null; }
    if (state.speechSource) { state.speechSource.onended = null; try { state.speechSource.stop(); } catch (e) {} state.speechSource = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    var p = state.player;
    if (p) {
      p.pause();
      // Do not reset/reload the unlocked media element between voice turns.
      if (reset) { p.removeAttribute("src"); p.load(); state.audioPrimed = false; }
    }
    releaseSpeechUrl();
    markPreview("");
  }
  function trimForSpeech(text) {
    var t = String(text || "").replace(/```[\s\S]*?```/g, " (code is on screen) ").replace(/\s+/g, " ").trim();
    return t.length > 1200 ? t.slice(0, 1200) : t;
  }

  function setMic(mode) {
    if (state.live) mode = "idle";
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

  function listenWithWebSpeech() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setMic("idle");
      showMicNote("This browser has no microphone. Type in the box instead.");
      return;
    }
    unlock();
    var rec = new SR();
    state.webRec = rec;
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = function (ev) {
      var said = "";
      try { said = ev.results[0][0].transcript || ""; } catch (e) { said = ""; }
      said = String(said).trim();
      if (!said) { setMic("idle"); return; }
      state.session = true;
      state.pendingTurn = true;
      var box = $("everyday");
      if (box) box.value = said;
      var form = $("composer");
      if (form) form.requestSubmit();
    };
    rec.onerror = function () {
      setMic("idle");
      showMicNote("The microphone did not start. Type in the box instead.");
    };
    rec.onend = function () {
      state.webRec = null;
      var b = $("micButton");
      if (b && b.dataset.state === "listening") setMic("idle");
    };
    setMic("listening");
    try { rec.start(); } catch (e) {
      setMic("idle");
      showMicNote("The microphone did not start. Type in the box instead.");
    }
  }

  async function startListening() {
    unlock();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === "undefined") {
      listenWithWebSpeech();
      return;
    }
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      showMicNote("Microphone permission was denied or the microphone is unavailable. Allow microphone access, then retry.");
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
      var res = await fetch(apiUrl("/api/voice/transcribe"), voiceRequest({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio: audio, mime: type.split(";")[0] })
      }));
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

  function signedIn() {
    return document.documentElement.getAttribute("data-simko-signed") === "1";
  }
  function showMicNote(text) {
    voiceNote(text);
    var hint = $("micHint");
    if (!hint) return;
    hint.hidden = false;
    hint.textContent = text;
  }
  function say(text, force) {
    if (!force && !state.session && !state.live) return;
    var line = trimForSpeech(text);
    if (!line) {
      setMic("idle");
      if (state.live) listenTurn(state.liveGen);
      return;
    }
    lastSpoken = line;
    voiceNote("");
    if (state.muted) {
      if (state.live) { setLivePhase("speaking"); resumeLiveAfterSpeech(); }
      else setMic("idle");
      return;
    }
    if (state.live) {
      setLivePhase("speaking");
      enableMic(false);
      stopRecognition();
    }
    if (!signedIn()) {
      showMicNote("Sign in to hear Simko SI. You can still type.");
      fallbackSpeak(line);
      return;
    }
    setMic("speaking");
    play(speakUrl({ voice: state.voice, speed: state.speed.toFixed(2), text: line }));
  }

  function micTap() {
    var b = $("micButton");
    var mode = b ? b.dataset.state : "idle";
    if (state.live) stopLive();
    if (mode === "off") { setReply("Voice needs Grok set up on the computer Simko SI runs from."); return; }
    if (mode === "listening") {
      if (state.recorder) state.recorder.stop();
      if (state.webRec) { try { state.webRec.stop(); } catch (e) {} }
      return;
    }
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
    lastSpoken = "Hello. I am " + (name || "Coral") + ".";
    if (!signedIn()) {
      showMicNote("Sign in to hear this voice. A browser voice will try.");
      fallbackSpeak(lastSpoken);
      return;
    }
    play(speakUrl({ voice: id, speed: state.speed.toFixed(2), preview: 1 }));
  }

  function validVoice(id) { return (state.voices.length ? state.voices : SEA).some(function (v) { return v.id === id; }); }
  function contextKey(id) { return VOICE_KEY + ":chat:" + id; }
  function setContext(session) {
    var id = session && session.id && String(session.id).indexOf("demo-") !== 0 ? String(session.id) : "";
    if (state.contextId && state.contextId !== id && state.live) stopLive();
    state.contextId = id;
    var pending = id ? load(contextKey(id) + ":pending", "") : "";
    var assigned = session && session.voice_id;
    var local = id ? load(contextKey(id), "") : "";
    var voice = validVoice(pending) ? pending : validVoice(assigned) ? assigned : validVoice(local) ? local : load(VOICE_KEY, "coral");
    choose(validVoice(voice) ? voice : "coral", { persist: false });
    if (id && validVoice(pending)) choose(pending); // Retry a device-only override.
  }
  function choose(id, options) {
    if (!validVoice(id)) return false;
    options = options || {};
    state.voice = id;
    var contextId = state.contextId || "";
    if (options.persist !== false) {
      save(VOICE_KEY, id);
      if (contextId) {
        save(contextKey(contextId), id); save(contextKey(contextId) + ":pending", id);
        state.voiceSaveSeq = (state.voiceSaveSeq || 0) + 1;
        var saveSeq = state.voiceSaveSeq;
        state.contextSaveSeq = state.contextSaveSeq || {};
        state.contextSaveSeq[contextId] = saveSeq;
        var body = { op: "set-voice", session_id: contextId, voice_id: id, child_id: window.simcoChildId || undefined };
        // Serialize saves per page so rapid selection cannot persist out of order.
        state.voiceSave = (state.voiceSave || Promise.resolve()).catch(function () {}).then(async function () {
          try {
            var response = await fetch(apiUrl("/api/sessions"), voiceRequest({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
            var data = await response.json();
            if (!response.ok || !data.ok || data.voice_id !== id) throw new Error("save-failed");
            if (state.contextSaveSeq[contextId] === saveSeq) save(contextKey(contextId) + ":pending", "");
            document.dispatchEvent(new CustomEvent("simco:voice-saved", { detail: { id: contextId, voice_id: id } }));
          } catch (e) {
            if (state.contextId === contextId && state.voice === id) voiceNote("Voice selected on this device; server saving failed. It will retry when this chat is opened.");
          }
        });
      }
    }
    var list = $("voiceList");
    if (list) list.querySelectorAll("button.voicePick").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.voice === id ? "true" : "false"); });
    var now = $("voiceNow"); if (now) now.textContent = currentName();
    var quick = $("liveVoiceSelect"); if (quick) quick.value = id;
    revealPicked();
    return true;
  }

  function paint() {
    var quick = $("liveVoiceSelect");
    if (quick) {
      quick.textContent = "";
      state.voices.forEach(function (v) { var option = document.createElement("option"); option.value = v.id; option.textContent = v.name + " — " + v.tone; quick.appendChild(option); });
    }
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
    choose(state.voice, { persist: false });
    paintSpeed();
  }

  function paintSpeed() {
    var quick = $("liveVoiceSpeed"), quickOut = $("liveVoiceSpeedOut");
    if (quick) { quick.min = state.min; quick.max = state.max; quick.value = state.speed; }
    if (quickOut) quickOut.textContent = state.speed.toFixed(2).replace(/0$/, "") + "×";
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
    var box = $("everyday");
    if (box) box.addEventListener("input", paintGo);
    var live = $("liveVoice");
    if (live) live.addEventListener("click", onLiveBoxClick);
    var liveClose = $("liveVoiceClose");
    if (liveClose) liveClose.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      stopLive();
    });
    var gear = $("liveVoiceGear");
    if (gear) gear.addEventListener("click", function () {
      var panel = $("liveVoiceSettings");
      panel.hidden = !panel.hidden;
      gear.setAttribute("aria-expanded", String(!panel.hidden));
      if (!panel.hidden) $("liveVoiceSelect").focus();
    });
    var micToggle = $("liveVoiceMic");
    if (micToggle) micToggle.addEventListener("click", function () {
      if (!state.live) return;
      unlock();
      if (state.livePhase === "error") { state.micPaused = false; listenTurn(state.liveGen); return; }
      state.micPaused = !state.micPaused;
      if (state.micPaused) {
        stopRecognition(); stopServerRec(); enableMic(false);
        if (state.livePhase === "listening") setLivePhase("paused");
      } else if (state.livePhase === "paused") listenTurn(state.liveGen);
      paintVoiceControls();
    });
    var mute = $("liveVoiceMute");
    if (mute) mute.addEventListener("click", function () {
      state.muted = !state.muted;
      if (!state.muted) unlock();
      if (state.muted) { stopSpeaking(); resumeLiveAfterSpeech(); }
      paintVoiceControls();
    });
    var quick = $("liveVoiceSelect");
    if (quick) quick.addEventListener("change", function () { choose(quick.value); });
    var quickSpeed = $("liveVoiceSpeed");
    if (quickSpeed) quickSpeed.addEventListener("input", function () {
      state.speed = Math.min(state.max, Math.max(state.min, parseFloat(quickSpeed.value) || 1));
      save(SPEED_KEY, state.speed); paintSpeed();
    });
    if (live) live.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var settings = $("liveVoiceSettings");
      if (settings && !settings.hidden) { settings.hidden = true; gear.setAttribute("aria-expanded", "false"); gear.focus(); }
      else stopLive();
    });
    paintGo();
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
      if (data && Array.isArray(data.voices) && data.voices.length) {
        state.voices = data.voices;
        state.min = data.min_speed || 0.7;
        state.max = data.max_speed || 1.5;
        if (!load(SPEED_KEY, "")) state.speed = data.default_speed || 1;
        if (!state.voices.some(function (v) { return v.id === state.voice; })) state.voice = data.default_voice || "coral";
      }
    } catch (e) {}
    if (!state.voices.length) state.voices = SEA.slice();
    state.ready = true;
    paint();
    setMic("idle");
  }

  function paintGo() {
    var go = $("go");
    var box = $("everyday");
    if (!go) return;
    var has = !!(box && String(box.value || "").trim());
    go.classList.toggle("has-text", has);
    go.classList.toggle("is-live", !!state.live);
    var label = has ? "Send" : (state.live ? "Stop voice conversation" : "Start voice conversation");
    go.setAttribute("aria-label", label);
    go.title = label;
  }

  function voiceNote(text) {
    var note = $("liveVoiceNote");
    if (note) { note.textContent = text || ""; note.hidden = !text; }
  }

  function paintVoiceControls() {
    var mic = $("liveVoiceMic"), mute = $("liveVoiceMute");
    var retry = state.livePhase === "error";
    if (mic) {
      mic.setAttribute("aria-pressed", String(!state.micPaused && !retry));
      mic.setAttribute("aria-label", retry ? "Retry microphone" : state.micPaused ? "Resume microphone" : "Pause microphone");
      mic.title = mic.getAttribute("aria-label");
    }
    if (mute) { mute.setAttribute("aria-pressed", String(state.muted)); mute.setAttribute("aria-label", state.muted ? "Unmute speaker" : "Mute speaker"); mute.title = mute.getAttribute("aria-label"); }
  }

  function liveError(message) {
    if (!state.live) return;
    stopRecognition(); stopServerRec(); enableMic(false);
    setLivePhase("error");
    voiceNote(message + " Tap the microphone to retry, or type below.");
  }

  function setLivePhase(phase) {
    state.livePhase = phase;
    var box = $("liveVoice");
    var label = $("liveVoiceState");
    if (box) {
      box.hidden = !state.live;
      box.dataset.phase = phase;
    }
    if (label) {
      label.textContent = phase === "listening" ? "Listening…" : phase === "thinking" ? "Thinking…" : phase === "speaking" ? "Speaking…" : phase === "paused" ? "Microphone paused" : phase === "error" ? "Please retry" : "";
    }
    paintVoiceControls();
    paintGo();
  }

  function enableMic(on) {
    if (!state.vizStream) return;
    state.vizStream.getTracks().forEach(function (track) { track.enabled = !!on && !state.micPaused; });
  }

  function stopRecognition() {
    var rec = state.liveRec;
    state.liveRec = null;
    if (!rec) return;
    rec.onresult = null;
    rec.onerror = null;
    rec.onend = null;
    try { if (rec.abort) rec.abort(); else rec.stop(); } catch (e) {}
  }

  function stopServerRec() {
    clearTimeout(state.serverMaxTimer);
    clearTimeout(state.serverQuietTimer);
    if (state.transcribeAbort) { state.transcribeAbort.abort(); state.transcribeAbort = null; }
    var rec = state.serverRec;
    state.serverRec = null;
    if (state.serverSilence) cancelAnimationFrame(state.serverSilence);
    state.serverSilence = 0;
    if (!rec) return;
    rec.onstop = null;
    rec.ondataavailable = null;
    rec.onerror = null;
    try { if (rec.state === "recording") rec.stop(); } catch (e) {}
  }

  function stopViz() {
    if (state.vizRaf) cancelAnimationFrame(state.vizRaf);
    state.vizRaf = 0;
    if (state.vizStream) {
      state.vizStream.getTracks().forEach(function (track) { try { track.stop(); } catch (e) {} });
      state.vizStream = null;
    }
    state.analyser = null;
  }

  function stopLive() {
    if (state.live) traceVoice("closed");
    state.live = false;
    state.liveGen = (state.liveGen || 0) + 1;
    state.livePhase = "off";
    state.session = false;
    state.pendingTurn = false;
    stopRecognition();
    stopServerRec();
    stopViz();
    stopSpeaking(true);
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    var box = $("liveVoice");
    if (box) box.hidden = true;
    var settings = $("liveVoiceSettings"), gear = $("liveVoiceGear");
    if (settings) settings.hidden = true;
    if (gear) gear.setAttribute("aria-expanded", "false");
    voiceNote("");
    if (state.returnFocus && state.returnFocus.focus) state.returnFocus.focus();
    paintGo();
    setMic("idle");
  }

  function resumeLiveAfterSpeech() {
    if (!state.live || state.livePhase !== "speaking") return;
    listenTurn(state.liveGen);
  }

  function toggleLive() {
    if (state.live) { stopLive(); return; }
    if (!signedIn()) {
      if (window.simcoApp && window.simcoApp.needAccount) window.simcoApp.needAccount();
      else showMicNote("Sign in to talk with Simko SI. You can still type.");
      return;
    }
    unlock();
    state.returnFocus = document.activeElement;
    state.micPaused = false;
    voiceNote("");
    state.live = true;
    state.liveGen = (state.liveGen || 0) + 1;
    var gen = state.liveGen;
    var panel = $("liveVoice");
    if (panel) panel.hidden = false;
    listenTurn(gen);
  }

  function onLiveBoxClick(event) {
    if (event.target && event.target.closest && event.target.closest("button, select, input, #liveVoiceSettings")) return;
    if (!state.live || state.livePhase !== "speaking") return;
    stopSpeaking();
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    listenTurn(state.liveGen);
  }

  function submitTranscript(said, gen) {
    if (!state.live || gen !== state.liveGen) return;
    said = String(said || "").trim();
    traceVoice("transcript_submit", said ? "" : "empty");
    if (!said) { listenTurn(gen); return; }
    setLivePhase("thinking");
    enableMic(false);
    stopRecognition();
    stopServerRec();
    state.session = true;
    state.pendingTurn = true;
    var box = $("everyday");
    if (box) {
      box.value = said;
      paintGo();
    }
    var form = $("composer");
    if (form && form.requestSubmit) form.requestSubmit();
  }

  function startBars() {
    var bars = document.querySelectorAll("#liveBars i");
    var data = state.analyser ? new Uint8Array(state.analyser.frequencyBinCount) : null;
    if (state.vizRaf) cancelAnimationFrame(state.vizRaf);
    var frames = 0;
    var tick = function () {
      if (!state.live) return;
      frames += 1;
      var holder = $("liveBars");
      if (holder) holder.dataset.tick = String(frames);
      var level = state.livePhase === "speaking" ? 0.62 : state.livePhase === "thinking" ? 0.22 : 0.16;
      if (data && state.analyser && state.livePhase === "listening") {
        try {
          state.analyser.getByteFrequencyData(data);
          var sum = 0;
          for (var i = 0; i < data.length; i++) sum += data[i];
          var measured = (sum / data.length) / 90;
          if (measured > level) level = Math.min(1, measured);
        } catch (e) {}
      }
      var now = (window.performance && performance.now) ? performance.now() : Date.now();
      for (var b = 0; b < bars.length; b++) {
        var wobble = 0.35 + 0.65 * Math.abs(Math.sin(now / 170 + b * 0.9));
        bars[b].style.height = Math.round(14 + level * 86 * wobble) + "%";
      }
      state.vizRaf = requestAnimationFrame(tick);
    };
    state.vizRaf = requestAnimationFrame(tick);
  }

  function openViz() {
    var gen = state.liveGen;
    if (state.vizStream && state.vizStream.getTracks().some(function (track) { return track.readyState === "live"; })) {
      enableMic(true);
      startBars();
      return Promise.resolve();
    }
    var devices = navigator.mediaDevices;
    if (!devices || !devices.getUserMedia) {
      liveError("This browser cannot access a microphone. Use a supported browser over HTTPS.");
      return Promise.resolve();
    }
    if (state.vizOpening) return state.vizOpening;
    traceVoice("mic_request");
    var opening = devices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }).then(function (stream) {
      if (!state.live || gen !== state.liveGen) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      state.vizStream = stream;
      traceVoice("mic_ready");
      enableMic(!state.micPaused);
      try {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) {
          state.vizCtx = state.vizCtx || state.audioCtx || new Ctx();
          if (state.vizCtx.state === "suspended" && state.vizCtx.resume) state.vizCtx.resume();
          var src = state.vizCtx.createMediaStreamSource(stream);
          var an = state.vizCtx.createAnalyser();
          an.fftSize = 256;
          src.connect(an);
          state.analyser = an;
        }
      } catch (e) {}
      startBars();
    }).catch(function (error) {
      if (!state.live || gen !== state.liveGen) return;
      traceVoice("mic_error", error && error.name);
      liveError(error && (error.name === "NotAllowedError" || error.name === "SecurityError")
        ? "Microphone permission was denied. Allow microphone access in your browser."
        : "The microphone is unavailable. Check that it is connected and not in use.");
    }).finally(function () { if (state.vizOpening === opening) state.vizOpening = null; });
    state.vizOpening = opening;
    return opening;
  }

  function startWebRec(gen) {
    if (!state.live || gen !== state.liveGen || state.livePhase !== "listening") return;
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { liveError("This browser cannot record or recognize speech."); return; }
    stopRecognition();
    var rec = new SR();
    state.liveRec = rec;
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    rec.onresult = function (ev) {
      if (!state.live || gen !== state.liveGen) return;
      var said = "";
      try { said = ev.results[0][0].transcript || ""; } catch (e) { said = ""; }
      stopRecognition();
      submitTranscript(said, gen);
    };
    rec.onerror = function (ev) {
      if (!state.live || gen !== state.liveGen || state.livePhase !== "listening") return;
      var code = ev && ev.error;
      traceVoice("webspeech_error", code);
      if (code === "aborted") return;
      if (code === "not-allowed" || code === "service-not-allowed") { liveError("Microphone permission was denied. Allow microphone access in your browser."); return; }
      if (code === "no-speech") { liveError("No speech was detected."); return; }
      stopRecognition();
      liveError("Speech recognition failed. Try again or type below.");
    };
    rec.onend = function () {
      if (state.liveRec === rec) state.liveRec = null;
      if (state.live && gen === state.liveGen && state.livePhase === "listening") {
        setTimeout(function () {
          if (state.live && gen === state.liveGen && state.livePhase === "listening" && !state.liveRec) startWebRec(gen);
        }, 300);
      }
    };
    try { rec.start(); traceVoice("webspeech_start"); } catch (e) { traceVoice("webspeech_error", e.name); stopRecognition(); liveError("Speech recognition could not start. Try another browser or type below."); }
  }

  function watchServerSilence(rec, gen) {
    try {
      if (!state.analyser) return;
      var heard = false, quietSince = 0;
      var buf = new Uint8Array(state.analyser.fftSize || 256);
      var tick = function () {
        if (!state.live || gen !== state.liveGen || !rec || rec.state !== "recording") return;
        state.analyser.getByteTimeDomainData(buf);
        var peak = 0;
        for (var i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128));
        var now = Date.now();
        if (peak > 6) { heard = true; quietSince = 0; clearTimeout(state.serverQuietTimer); }
        else if (heard) {
          quietSince = quietSince || now;
          if (now - quietSince > 1200) { try { rec.stop(); } catch (e) {} return; }
        }
        state.serverSilence = requestAnimationFrame(tick);
      };
      state.serverSilence = requestAnimationFrame(tick);
    } catch (e) {}
  }

  function startServerRec(gen) {
    if (!state.live || gen !== state.liveGen || state.livePhase !== "listening") return;
    if (!state.vizStream || typeof MediaRecorder === "undefined") {
      liveError("This browser cannot record microphone audio.");
      return;
    }
    stopServerRec();
    var chunks = [];
    var rec;
    var types = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"];
    var mime = "";
    for (var i = 0; i < types.length; i++) if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) { mime = types[i]; break; }
    try { rec = mime ? new MediaRecorder(state.vizStream, { mimeType: mime }) : new MediaRecorder(state.vizStream); }
    catch (e) {
      traceVoice("mic_error", e.name);
      startWebRec(gen);
      return;
    }
    state.serverRec = rec;
    rec.ondataavailable = function (ev) { if (ev.data && ev.data.size) chunks.push(ev.data); };
    rec.onerror = function () { liveError("Microphone recording failed."); };
    rec.onstop = function () {
      traceVoice("recorder_stop");
      clearTimeout(state.serverMaxTimer); clearTimeout(state.serverQuietTimer);
      if (state.serverSilence) cancelAnimationFrame(state.serverSilence);
      if (state.serverRec === rec) state.serverRec = null;
      if (!state.live || gen !== state.liveGen || state.livePhase !== "listening") return;
      var blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      if (!blob.size) { liveError("No audio was recorded."); return; }
      setLivePhase("thinking");
      enableMic(false);
      var reader = new FileReader();
      reader.onload = async function () {
        if (!state.live || gen !== state.liveGen) return;
        var audio = String(reader.result || "").split(",")[1] || "";
        var data = null;
        var controller = new AbortController();
        state.transcribeAbort = controller;
        var timeout = setTimeout(function () { controller.abort(); }, 50000);
        traceVoice("transcribe_sent");
        try {
          var res = await fetch(apiUrl("/api/voice/transcribe"), voiceRequest({
            signal: controller.signal,
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ audio: audio, mime: (rec.mimeType || "audio/webm").split(";")[0] })
          }));
          data = await res.json();
          traceVoice(data && data.ok ? "transcribe_reply" : "transcribe_error", "", res.status);
        } catch (err) { traceVoice("transcribe_error", err.name); data = null; }
        finally { clearTimeout(timeout); if (state.transcribeAbort === controller) state.transcribeAbort = null; }
        if (!state.live || gen !== state.liveGen) return;
        var text = data && data.ok && data.text ? String(data.text).trim() : "";
        if (!text) { liveError((data && (data.everyday || data.error)) || "Transcription failed or no speech was detected."); return; }
        submitTranscript(text, gen);
      };
      reader.onerror = function () { if (state.live && gen === state.liveGen) liveError("The recording could not be read."); };
      reader.readAsDataURL(blob);
    };
    try { rec.start(250); traceVoice("recorder_start"); } catch (e) {
      liveError("The microphone could not start recording.");
      return;
    }
    state.serverMaxTimer = setTimeout(function () { if (state.serverRec === rec && rec.state === "recording") rec.stop(); }, 45000);
    // Do not discard a quiet but valid recording merely because VAD did not
    // cross its threshold. Let server STT decide whether it contains speech.
    state.serverQuietTimer = setTimeout(function () { if (state.serverRec === rec && rec.state === "recording") rec.stop(); }, 10000);
    watchServerSilence(rec, gen);
  }

  function listenTurn(gen) {
    if (!state.live || gen !== state.liveGen) return;
    if (state.micPaused) { setLivePhase("paused"); return; }
    if (state.livePhase === "error" || state.livePhase === "paused") voiceNote("");
    if (state.livePhase === "listening" && (state.liveRec || (state.serverRec && state.serverRec.state === "recording"))) return;
    stopRecognition();
    stopServerRec();
    setLivePhase("listening");
    enableMic(true);
    startBars();
    openViz().then(function () {
      if (!state.live || gen !== state.liveGen || state.livePhase !== "listening") return;
      if (typeof MediaRecorder !== "undefined") startServerRec(gen);
      else startWebRec(gen);
    });
  }

  window.simcoVoice = {
    // chat.html calls these so voice turns use the exact same send/reply code as typing.
    consumeTurn: function () {
      var v = state.pendingTurn;
      state.pendingTurn = false;
      if (state.live) {
        state.session = true;
        if (state.livePhase === "listening") {
          stopRecognition();
          stopServerRec();
          enableMic(false);
          setLivePhase("thinking");
        }
        return true;
      }
      if (!v) state.session = false;
      return v;
    },
    reply: function (text) {
      if (state.live || state.session) { say(text, !!state.live); return; }
      // v6: typed turns are spoken too while the voice picker is on screen and the speaker is not muted.
      var picker = $("voicePicker");
      if (picker && !picker.hidden && picker.offsetParent !== null && !state.muted) { say(text, true); return; }
      var b = $("micButton");
      if (b && b.dataset.state === "thinking") setMic("idle");
    },
    toggleLive: toggleLive,
    stopLive: stopLive,
    trace: traceVoice,
    say: say,
    stop: stopSpeaking,
    choose: choose,
    setContext: setContext,
    state: state,
    boot: boot
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
