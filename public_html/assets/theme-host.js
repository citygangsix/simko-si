(function () {
  var THEMES = [
    { id: "reef-live", name: "Reef", colors: ["#03141c", "#ff7f6a", "#7dcea0"] },
    { id: "plain", name: "Plain", colors: ["#f7f4ee", "#1b2430", "#c4b8a5"] }
  ];

  function current() {
    return document.documentElement.getAttribute("data-theme") || "reef-live";
  }

  function apply(id) {
    document.documentElement.setAttribute("data-theme", id);
    var link = document.getElementById("themeStylesheet");
    var meta = document.querySelector('meta[name="simko-build"]');
    var build = meta ? (meta.getAttribute("content") || "") : "";
    if (link) link.href = "/themes/" + encodeURIComponent(id) + "/theme.css" + (build ? "?v=" + encodeURIComponent(build) : "");
    try { localStorage.setItem("simcoTheme", id); } catch (e) {}
    paint();
  }

  function paint() {
    var list = document.getElementById("themeList");
    if (!list) return;
    var selected = current();
    list.replaceChildren();
    THEMES.forEach(function (theme) {
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", theme.id === selected ? "true" : "false");
      var swatch = document.createElement("span");
      swatch.className = "themeSwatch";
      swatch.style.background = "linear-gradient(90deg," + theme.colors.join(",") + ")";
      var label = document.createElement("span");
      label.textContent = theme.name;
      button.append(swatch, label);
      button.addEventListener("click", function () { apply(theme.id); });
      list.appendChild(button);
    });
  }

  window.simcoThemes = {
    syncFromServer: function () {},
    apply: apply,
    boot: paint
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paint);
  else paint();
})();
