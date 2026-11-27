/* Reef Live motion. Real reef video loops (wide + tall) when the device can play them,
   otherwise vector art and a DPR-scaled canvas. requestAnimationFrame, no fps cap. */
(function () {
  var raf = 0;
  var frames = 0;
  var started = 0;

  function stats() {
    window.simcoFrameStats = {
      mode: "requestAnimationFrame",
      capped: false,
      frames: frames,
      started: started,
      fps: started ? frames / ((performance.now() - started) / 1000) : 0,
      dpr: window.devicePixelRatio || 1
    };
  }

  function turtle() {
    return ''
      + '<svg class="reef-turtle reef-mover" viewBox="0 0 220 90" aria-hidden="true">'
      + '<g fill="none">'
      + '<ellipse cx="78" cy="58" rx="28" ry="8" fill="#c9b48a" opacity="0.9"/>'
      + '<path d="M40 48c8 10 22 16 40 14 6-8 4-18-2-24" fill="#6d8a45"/>'
      + '<path d="M118 50c10 6 22 4 30-4 2 10-6 18-18 20" fill="#5d7a3c"/>'
      + '<ellipse cx="92" cy="46" rx="46" ry="24" fill="#7d8f48"/>'
      + '<ellipse cx="92" cy="44" rx="34" ry="16" fill="#5c6b34"/>'
      + '<path d="M70 36h14M86 32v16M104 34h16M112 30v18" stroke="#3e4a24" stroke-width="1.4"/>'
      + '<ellipse cx="148" cy="40" rx="16" ry="10" fill="#d7c49a"/>'
      + '<circle cx="156" cy="38" r="1.6" fill="#1b2414"/>'
      + '<path d="M162 40c8 1 12 4 14 8" stroke="#d7c49a" stroke-width="2" stroke-linecap="round"/>'
      + '<path d="M70 58c-16 8-28 6-36-2 10 2 20 0 28-6z" fill="#6d8a45"/>'
      + '</g></svg>';
  }

  function fish() {
    return ''
      + '<svg class="reef-fish reef-mover" viewBox="0 0 120 64" aria-hidden="true">'
      + '<g>'
      + '<polygon points="8,32 28,16 28,48" fill="#f2b43a"/>'
      + '<ellipse cx="62" cy="32" rx="34" ry="16" fill="#f7f7f4"/>'
      + '<path d="M40 20v24M54 18v28M70 20v24" stroke="#1c2430" stroke-width="5"/>'
      + '<path d="M48 32h28" stroke="#f2b43a" stroke-width="4"/>'
      + '<polygon points="92,32 112,16 112,48" fill="#f2b43a"/>'
      + '<circle cx="78" cy="28" r="2" fill="#1c2430"/>'
      + '</g></svg>';
  }

  function kelp(side) {
    var origin = side === "left" ? "left" : "right";
    return ''
      + '<svg class="reef-kelp reef-mover reef-kelp-' + side + '" viewBox="0 0 80 400" aria-hidden="true" style="transform-origin:' + origin + ' bottom">'
      + '<path d="M40 400C20 300 60 220 30 80" fill="none" stroke="#1f8a4c" stroke-width="10" stroke-linecap="round"/>'
      + '<path d="M54 400C70 280 30 180 58 40" fill="none" stroke="#2ea86a" stroke-width="7" stroke-linecap="round"/>'
      + '</svg>';
  }

  function resizeCanvas(canvas) {
    var dpr = Math.max(1, window.devicePixelRatio || 1);
    var width = canvas.clientWidth || window.innerWidth;
    var height = canvas.clientHeight || window.innerHeight;
    var bw = Math.max(1, Math.round(width * dpr));
    var bh = Math.max(1, Math.round(height * dpr));
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw;
      canvas.height = bh;
    }
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, width: width, height: height, dpr: dpr };
  }

  function drawPlate(canvas, now) {
    var view = resizeCanvas(canvas);
    var ctx = view.ctx;
    var t = now / 1000;
    ctx.clearRect(0, 0, view.width, view.height);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (var i = 0; i < 4; i++) {
      var x = view.width * (0.18 + i * 0.2);
      ctx.fillStyle = "rgba(255,246,216," + (0.05 + 0.04 * Math.sin(t * 0.7 + i)) + ")";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + 36, 0);
      ctx.lineTo(x + 90, view.height);
      ctx.lineTo(x - 40, view.height);
      ctx.fill();
    }
    ctx.restore();
    ctx.save();
    for (var c = 0; c < 5; c++) {
      var cx = (view.width * (0.15 + c * 0.18) + Math.sin(t * 0.6 + c) * 18);
      ctx.fillStyle = "rgba(255,248,220," + (0.12 + 0.08 * Math.sin(t + c)) + ")";
      ctx.beginPath();
      ctx.ellipse(cx, view.height * 0.86, 70, 12, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function place(el, styles) {
    el.style.position = "absolute";
    el.style.pointerEvents = "none";
    Object.keys(styles).forEach(function (key) { el.style[key] = styles[key]; });
  }

  /* Real reef loops: wide (1280x720) for unfolded / desktop, tall (720x1280)
     for the folded cover screen and narrow phones. Muted, inline, looped,
     and paused whenever motion is off (hidden, idle, reduced motion, low
     battery, Plain). The still plate stays underneath as the poster. */
  var VIDEO_WIDE = "/themes/reef-live/video/reef-wide-720p.mp4";
  var VIDEO_TALL = "/themes/reef-live/video/reef-tall-720p.mp4";
  var NARROW_QUERY = "(max-width: 640px)";

  function wantsTall() {
    try {
      return window.matchMedia(NARROW_QUERY).matches;
    } catch (err) {
      return (window.innerWidth || 0) <= 640;
    }
  }

  function videoAllowed() {
    try {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    } catch (err) {}
    var probe = document.createElement("video");
    return !!(probe.canPlayType && probe.canPlayType('video/mp4; codecs="avc1.4d401f"'));
  }

  function makeVideo() {
    if (!videoAllowed()) return null;
    var video = document.createElement("video");
    video.id = "reefVideo";
    video.muted = true;
    video.defaultMuted = true;
    video.loop = true;
    video.playsInline = true;
    video.autoplay = false;
    video.preload = "auto";
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.setAttribute("disablepictureinpicture", "");
    video.setAttribute("aria-hidden", "true");
    return video;
  }

  function motionOn() {
    return document.documentElement.getAttribute("data-theme") === "reef-live"
      && document.documentElement.getAttribute("data-motion") !== "off";
  }

  function bindVideo(video) {
    var root = document.documentElement;
    function pickSource() {
      var tall = wantsTall();
      var src = tall ? VIDEO_TALL : VIDEO_WIDE;
      root.setAttribute("data-reef-loop", tall ? "tall" : "wide");
      if (video.getAttribute("src") !== src) {
        video.setAttribute("src", src);
        video.load();
      }
      sync();
    }
    function sync() {
      if (motionOn()) {
        var played = video.play();
        if (played && played.catch) played.catch(function () {});
      } else if (!video.paused) {
        video.pause();
      }
    }
    video.addEventListener("playing", function () { root.classList.add("reef-video-on"); });
    video.addEventListener("error", function () {
      root.classList.remove("reef-video-on");
      video.remove();
    });
    var mq = null;
    try { mq = window.matchMedia(NARROW_QUERY); } catch (err) { mq = null; }
    if (mq && mq.addEventListener) mq.addEventListener("change", pickSource);
    else if (mq && mq.addListener) mq.addListener(pickSource);
    window.addEventListener("resize", pickSource);
    var watch = new MutationObserver(sync);
    watch.observe(root, { attributes: true, attributeFilter: ["data-motion", "data-theme"] });
    video._simcoCleanup = function () {
      watch.disconnect();
      window.removeEventListener("resize", pickSource);
      if (mq && mq.removeEventListener) mq.removeEventListener("change", pickSource);
      else if (mq && mq.removeListener) mq.removeListener(pickSource);
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
    pickSource();
  }

  function mount() {
    if (document.getElementById("themeStage")) return;
    var stage = document.createElement("div");
    stage.id = "themeStage";
    stage.setAttribute("aria-hidden", "true");
    var picture = document.createElement("picture");
    picture.id = "reefPlate";
    picture.innerHTML = ''
      + '<source media="(max-width: 640px), (max-height: 560px)" type="image/avif" srcset="/themes/reef-live/bg/portrait-640.avif 1x, /themes/reef-live/bg/portrait-1280.avif 2x">'
      + '<source media="(max-width: 640px), (max-height: 560px)" type="image/webp" srcset="/themes/reef-live/bg/portrait-640.webp 1x, /themes/reef-live/bg/portrait-1280.webp 2x">'
      + '<source type="image/avif" srcset="/themes/reef-live/bg/landscape-640.avif 1x, /themes/reef-live/bg/landscape-1280.avif 2x">'
      + '<source type="image/webp" srcset="/themes/reef-live/bg/landscape-640.webp 1x, /themes/reef-live/bg/landscape-1280.webp 2x">'
      + '<img alt="" src="/themes/reef-live/bg/landscape-1280.jpg" srcset="/themes/reef-live/bg/landscape-640.jpg 1x, /themes/reef-live/bg/landscape-1280.jpg 2x">';
    var canvas = document.createElement("canvas");
    canvas.id = "reefCaustics";
    var layer = document.createElement("div");
    layer.id = "reefVectors";
    layer.innerHTML = kelp("left") + kelp("right") + turtle() + fish()
      + '<span class="reef-bubble reef-mover"></span><span class="reef-bubble reef-mover"></span><span class="reef-bubble reef-mover"></span>';
    stage.appendChild(picture);
    var video = makeVideo();
    if (video) stage.appendChild(video);
    stage.appendChild(canvas);
    stage.appendChild(layer);
    document.body.appendChild(stage);
    if (video) bindVideo(video);
    var nodes = {
      turtle: stage.querySelector(".reef-turtle"),
      fish: stage.querySelector(".reef-fish"),
      kelpL: stage.querySelector(".reef-kelp-left"),
      kelpR: stage.querySelector(".reef-kelp-right"),
      bubbles: stage.querySelectorAll(".reef-bubble")
    };
    place(nodes.turtle, { right: "6%", top: "7%", width: "min(18rem, 34vw)", height: "auto" });
    place(nodes.fish, { left: "42%", top: "36%", width: "min(9rem, 22vw)", height: "auto" });
    place(nodes.kelpL, { left: "0", top: "0", height: "100%", width: "4.2rem" });
    place(nodes.kelpR, { right: "0", top: "0", height: "100%", width: "4.2rem" });
    nodes.bubbles.forEach(function (bubble, index) {
      place(bubble, {
        left: (18 + index * 22) + "%",
        bottom: "8%",
        width: (8 + index * 3) + "px",
        height: (8 + index * 3) + "px",
        borderRadius: "50%",
        background: "rgba(255,255,255,0.55)"
      });
    });
    document.documentElement.classList.add("reef-plate-on");
    var watch = new MutationObserver(function () {
      var live = document.documentElement.getAttribute("data-theme") === "reef-live";
      var moving = document.documentElement.getAttribute("data-motion") !== "off";
      if (live && moving && !raf && document.getElementById("themeStage")) {
        raf = window.requestAnimationFrame(tick);
      }
    });
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-motion", "data-theme"] });
    frames = 0;
    started = 0;
    function tick(now) {
      var off = document.documentElement.getAttribute("data-motion") === "off"
        || document.documentElement.getAttribute("data-theme") !== "reef-live";
      if (!started) started = now;
      frames += 1;
      stats();
      if (off || document.documentElement.classList.contains("reef-video-on")) {
        raf = 0;
        return;
      }
      var t = now / 1000;
      nodes.turtle.style.transform = "translate(" + Math.sin(t * 0.6) * 14 + "px," + Math.cos(t * 0.45) * 8 + "px) rotate(" + Math.sin(t * 0.5) * 6 + "deg)";
      nodes.fish.style.transform = "translate(" + Math.sin(t * 0.8) * 16 + "px," + Math.cos(t * 0.7) * 6 + "px)";
      nodes.kelpL.style.transform = "rotate(" + Math.sin(t * 0.9) * 6 + "deg)";
      nodes.kelpR.style.transform = "rotate(" + Math.sin(t * 0.8 + 1) * -6 + "deg)";
      nodes.bubbles.forEach(function (bubble, index) {
        var rise = ((t * 28 + index * 40) % 220);
        bubble.style.transform = "translateY(" + (-rise) + "px)";
        bubble.style.opacity = String(Math.max(0, 1 - rise / 220));
      });
      drawPlate(canvas, now);
      raf = window.requestAnimationFrame(tick);
    }
    raf = window.requestAnimationFrame(tick);
    window.simcoThemeLayer = { mount: mount, unmount: unmount, dpr: window.devicePixelRatio || 1 };
  }

  function unmount() {
    if (raf) window.cancelAnimationFrame(raf);
    raf = 0;
    var video = document.getElementById("reefVideo");
    if (video && video._simcoCleanup) video._simcoCleanup();
    var stage = document.getElementById("themeStage");
    if (stage) stage.remove();
    document.documentElement.classList.remove("reef-plate-on");
    document.documentElement.classList.remove("reef-video-on");
    document.documentElement.removeAttribute("data-reef-loop");
  }

  window.simcoThemeLayer = { mount: mount, unmount: unmount, dpr: window.devicePixelRatio || 1 };
  if (document.documentElement.getAttribute("data-theme") === "reef-live") mount();
})();
