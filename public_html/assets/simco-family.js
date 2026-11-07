/* Parent and child screens. Loaded only when the family flag is on. */
(function () {
  var MARKS = {
    turtle: "🐢", dolphin: "🐬", octopus: "🐙", whale: "🐋",
    seahorse: "🐚", coral: "🪸", manta: "🐟", otter: "🦦"
  };
  var status = null;

  function $(id) { return document.getElementById(id); }

  function token() {
    return window.simcoUserToken || "";
  }

  function post(body) {
    var payload = Object.assign({ token: token() }, body);
    return fetch("/api/family", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (res) { return res.json(); });
  }

  function setError(message) {
    var line = $("familyError");
    if (!line) return;
    line.hidden = !message;
    line.textContent = message || "";
  }

  function showCard(id) {
    ["familyDash", "familyAdd", "familyPick"].forEach(function (name) {
      var card = $(name);
      if (card) card.hidden = name !== id;
    });
    var stage = $("familyStage");
    if (stage) stage.hidden = false;
    setError("");
  }

  function closeStage() {
    var stage = $("familyStage");
    if (stage) stage.hidden = true;
  }

  function paintChoices(data) {
    var avatar = $("childAvatar");
    var age = $("childAge");
    if (avatar && data.characters) {
      avatar.replaceChildren();
      Object.keys(data.characters).forEach(function (id) {
        var option = document.createElement("option");
        option.value = id;
        option.textContent = data.characters[id];
        avatar.appendChild(option);
      });
    }
    if (age && data.age_bands) {
      age.replaceChildren();
      data.age_bands.forEach(function (band) {
        var option = document.createElement("option");
        option.value = band;
        option.textContent = band;
        age.appendChild(option);
      });
    }
  }

  function paintDash(data) {
    status = data;
    var box = $("familyKids");
    if (!box) return;
    box.replaceChildren();
    var kids = data.children || [];
    if (!kids.length) {
      var empty = document.createElement("p");
      empty.className = "familyEmpty";
      empty.textContent = "No child profiles yet. Add one when you are ready.";
      box.appendChild(empty);
      return;
    }
    kids.forEach(function (kid) {
      var card = document.createElement("article");
      card.className = "familyKid";
      var title = document.createElement("h3");
      title.textContent = (MARKS[kid.avatar] || "💬") + " " + kid.display_name;
      var meta = document.createElement("p");
      meta.className = "familyMeta";
      meta.textContent = kid.character + " · " + kid.age_band;
      card.append(title, meta);
      var chats = kid.chats || [];
      if (!chats.length) {
        var none = document.createElement("p");
        none.className = "familyEmpty";
        none.textContent = "No chats yet.";
        card.appendChild(none);
      }
      chats.forEach(function (chat) {
        var row = document.createElement("div");
        row.className = "familyChat";
        var label = document.createElement("span");
        label.textContent = chat.title || "Chat";
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = "Delete";
        button.addEventListener("click", function () { removeChat(chat.id); });
        row.append(label, button);
        card.appendChild(row);
      });
      box.appendChild(card);
    });
  }

  function paintPicker(data) {
    var list = $("familyPickList");
    if (!list) return;
    list.replaceChildren();
    var mine = document.createElement("button");
    mine.type = "button";
    mine.className = "familyPerson";
    mine.innerHTML = "<b>👤</b><span>Just me</span>";
    mine.addEventListener("click", function () { chooseChild(0); });
    list.appendChild(mine);
    (data.children || []).forEach(function (kid) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "familyPerson";
      var mark = document.createElement("b");
      mark.textContent = MARKS[kid.avatar] || "💬";
      var name = document.createElement("span");
      name.textContent = kid.display_name;
      button.append(mark, name);
      button.addEventListener("click", function () { chooseChild(kid.id); });
      list.appendChild(button);
    });
  }

  function chooseChild(id) {
    window.simcoChildId = id || 0;
    if (!window.simcoChildId) window.simcoChildId = 0;
    if (!id) delete window.simcoChildId;
    window.dispatchEvent(new Event("simko-child"));
    closeStage();
  }

  function removeChat(id) {
    post({ op: "delete-chat", session_id: id }).then(function (data) {
      if (!data.ok) {
        setError(data.error || "That chat could not be deleted.");
        return;
      }
      return refresh();
    });
  }

  function refresh() {
    return post({ op: "status" }).then(function (data) {
      if (!data.ok) {
        setError(data.error || "Family details could not be loaded.");
        return data;
      }
      paintChoices(data);
      paintDash(data);
      paintPicker(data);
      return data;
    });
  }

  function openDash() {
    if (!token()) {
      var signIn = $("accountSignIn");
      if (signIn) signIn.click();
      return;
    }
    showCard("familyDash");
    refresh();
  }

  function boot() {
    if (document.documentElement.getAttribute("data-simko-family") !== "1") return;
    var open = $("familyOpen");
    if (open) open.hidden = false;
    if (open && !open.dataset.bound) {
      open.dataset.bound = "1";
      open.addEventListener("click", openDash);
    }
    var close = $("familyClose");
    if (close && !close.dataset.bound) {
      close.dataset.bound = "1";
      close.addEventListener("click", closeStage);
    }
    var addOpen = $("familyAddOpen");
    if (addOpen && !addOpen.dataset.bound) {
      addOpen.dataset.bound = "1";
      addOpen.addEventListener("click", function () { showCard("familyAdd"); });
    }
    var addClose = $("familyAddClose");
    if (addClose && !addClose.dataset.bound) {
      addClose.dataset.bound = "1";
      addClose.addEventListener("click", function () { showCard("familyDash"); });
    }
    var pickOpen = $("familyPickOpen");
    if (pickOpen && !pickOpen.dataset.bound) {
      pickOpen.dataset.bound = "1";
      pickOpen.addEventListener("click", function () { showCard("familyPick"); });
    }
    var pickClose = $("familyPickClose");
    if (pickClose && !pickClose.dataset.bound) {
      pickClose.dataset.bound = "1";
      pickClose.addEventListener("click", function () { showCard("familyDash"); });
    }
    var form = $("familyAddForm");
    if (form && !form.dataset.bound) {
      form.dataset.bound = "1";
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        post({
          op: "create-child",
          display_name: $("childName").value,
          avatar: $("childAvatar").value,
          age_band: $("childAge").value
        }).then(function (data) {
          if (!data.ok) {
            setError(data.error || "That child profile could not be saved.");
            showCard("familyAdd");
            return;
          }
          $("childName").value = "";
          showCard("familyDash");
          refresh();
        });
      });
    }
    if ($("authModal") && !$("authModal").hidden && window.simcoApp === undefined) {
      var row = $("parentConsentRow");
      if (row) row.hidden = false;
    }
  }

  window.simcoFamily = { boot: boot, open: openDash, refresh: refresh };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
