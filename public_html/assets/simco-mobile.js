/* Simko SI mobile + store-app helpers. Nothing here changes how the website looks.
   - Registers the offline service worker.
   - Inside the iOS App Store build (user agent contains "SimkoSIApp-iOS") Google sign-in is hidden,
     because Google blocks OAuth inside embedded web views and Apple then requires Sign in with Apple.
   - Inside the native apps, uses native haptics and the native share sheet when the Capacitor bridge is present. */
(function () {
  var ua = navigator.userAgent || '';
  var inIosApp = /SimkoSIApp-iOS/.test(ua);
  var inAndroidApp = /SimkoSIApp-Android/.test(ua) || document.referrer.indexOf('android-app://com.simkosi.app') === 0;
  if (inIosApp || inAndroidApp) document.documentElement.setAttribute('data-simko-app', inIosApp ? 'ios' : 'android');

  if ('serviceWorker' in navigator && (location.protocol === 'https:' || /^(localhost|127\.0\.0\.1)$/.test(location.hostname))) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
    });
  }

  if (inIosApp) {
    var oauth = {};
    Object.defineProperty(window, 'simkoOauth', {
      configurable: true,
      get: function () { return oauth; },
      set: function (v) { oauth = Object.assign({}, v || {}); oauth.google = false; }
    });
    var hideGoogle = function () {
      var g = document.getElementById('googleSignIn');
      if (g && !g.hidden) g.hidden = true;
    };
    document.addEventListener('DOMContentLoaded', hideGoogle);
    new MutationObserver(hideGoogle).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
  }

  var cap = window.Capacitor;
  if (cap && cap.isNativePlatform && cap.isNativePlatform()) {
    var plugins = cap.Plugins || {};
    document.addEventListener('click', function (e) {
      var t = e.target && e.target.closest ? e.target.closest('#go, #micButton, #turtleAskSend') : null;
      if (t && plugins.Haptics) plugins.Haptics.impact({ style: 'LIGHT' }).catch(function () {});
    }, true);
    if (plugins.Share && navigator.share === undefined) {
      navigator.share = function (data) { return plugins.Share.share({ title: data.title, text: data.text, url: data.url }); };
    }
  }
})();
