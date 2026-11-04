"use strict";
// The settings panel (Phase 3 box E3). One home for every name: the six
// field names are core/config_surface.py ui_keys() (E1), the body shape is
// GET/PUT /settings from core/util/settings.py (E2). The panel shows the
// five fields below plus the capture-passes slot index.html reserves for E5
// (#settings-capture-passes; this module never writes into it); every other
// row sits read-only under the collapsed <details id="settings-advanced">.
// Secrets are password inputs with a "show" toggle (decision: yes).
window.FlightSimSettings = (function () {
  // ui_keys() minus capture_passes, in E1's order; the slot is the sixth.
  const FIELDS = ["google_tiles_key", "cesium_status", "engine", "render_quality", "llm_key"];
  const READONLY = ["cesium_status", "engine"];
  const SECRETS = ["google_tiles_key", "llm_key"];
  const LABELS = {
    google_tiles_key: "Google tiles key",
    cesium_status: "Cesium for Unreal",
    engine: "Engine",
    render_quality: "Render quality",
    llm_key: "LLM key (Claude)",
    capture_passes: "Extra passes",
  };
  const RENDER_QUALITIES = ["measure", "beauty"];
  //: The missing-item messages, keyed by the row name GET /settings `missing`
  //: reports; each names the item and what fixes it.
  const MESSAGES = {
    google_tiles_key: "Google tiles key missing: paste it here once (Google Maps Platform key with the Map Tiles API)",
    llm_key: "LLM key missing: paste a Claude API key here once, or the compiler stays on the offline parser",
  };

  let root = null;
  let state = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  // The sentence for every missing row, keyed by row: the panel's own text
  // for a row it knows, the server's message for one it does not, and the
  // Cesium line (readonly.cesium_status, named with the engine) when the
  // plugin is absent.
  function messageFor(missing, readonly) {
    const out = {};
    (missing || []).forEach(m => {
      if (!m || !m.key) return;
      out[m.key] = MESSAGES[m.key] || m.message || (m.key + ": missing");
    });
    const cs = readonly && readonly.cesium_status;
    if (cs && cs.ok === false) {
      const version = cs.version || "(no pin)";
      const engine = String(readonly.engine || "").split(".").slice(0, 2).join(".");
      out.cesium_status = "Cesium for Unreal " + version + " not found for engine " + engine +
        ": install it from the Fab / Marketplace page into the engine's Plugins/Marketplace folder (" +
        (cs.message || "") + ")";
    }
    return out;
  }

  function readonlyText(key, body) {
    const ro = body.readonly || {};
    if (key === "engine") return ro.engine || body.settings.engine || "unknown";
    const cs = ro.cesium_status || body.settings.cesium_status || {};
    if (cs.ok) return (cs.version || "") + " installed";
    return cs.version ? cs.version + " pinned, not installed" : "no pin";
  }

  function fieldHtml(key, body, messages) {
    const env = body.env_override || {};
    const value = body.settings[key];
    const msg = messages[key];
    let control;
    if (READONLY.indexOf(key) >= 0) {
      control = `<span class="settings-ro" data-readonly="${esc(key)}">${esc(readonlyText(key, body))}</span>`;
    } else if (key === "render_quality") {
      control = `<select id="settings-${esc(key)}" name="${esc(key)}">` +
        RENDER_QUALITIES.map(q => `<option value="${q}"${q === value ? " selected" : ""}>${q}</option>`).join("") +
        `</select>`;
    } else if (SECRETS.indexOf(key) >= 0) {
      control = `<input id="settings-${esc(key)}" name="${esc(key)}" type="password" autocomplete="off" ` +
        `spellcheck="false" value="${esc(value || "")}">` +
        `<button type="button" class="settings-show" data-for="settings-${esc(key)}">show</button>`;
    } else {
      control = `<input id="settings-${esc(key)}" name="${esc(key)}" type="text" value="${esc(value || "")}">`;
    }
    const envNote = env[key] ? `<small class="settings-env">env override: ${esc(env[key])}</small>` : "";
    const msgHtml = msg ? `<div class="settings-msg" data-missing="${esc(key)}">${esc(msg)}</div>` : "";
    return `<div class="settings-field" data-field="${esc(key)}">` +
      `<label for="settings-${esc(key)}">${esc(LABELS[key] || key)}</label>` +
      `<div class="settings-control">${control}${envNote}</div>${msgHtml}</div>`;
  }

  function advancedHtml(body) {
    const env = body.env_override || {};
    const shown = FIELDS.concat(["capture_passes"]);
    const rows = Object.keys(body.settings || {}).filter(k => shown.indexOf(k) < 0 &&
      !(body.readonly && k in body.readonly)).sort();
    const trs = rows.map(k => {
      const v = body.settings[k];
      const text = Array.isArray(v) ? v.join(", ") : (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));
      const src = env[k] ? "env " + env[k] : "default";
      return `<tr data-advanced="${esc(k)}"><th>${esc(k)}</th><td>${esc(text)}</td><td class="dim">${esc(src)}</td></tr>`;
    }).join("");
    return `<p class="dim">Developer switches: set in the environment where the server runs, never in this file. ` +
      `FLIGHTSIM_GOOGLE_TILES=off is the only off switch for the tiles; the storm weather defaults stay on.</p>` +
      `<table class="settings-advanced-table"><tbody>${trs}</tbody></table>` +
      `<p class="dim">settings file: <code>${esc(body.path || "")}</code></p>`;
  }

  function render(body) {
    if (!root) return;
    state = body;
    const messages = messageFor(body.missing, body.readonly);
    const fields = root.querySelector("#settings-fields");
    fields.innerHTML = FIELDS.map(k => fieldHtml(k, body, messages)).join("");
    const status = root.querySelector("#settings-status");
    const missingKeys = Object.keys(messages);
    status.textContent = missingKeys.length ? "" : "all set";
    const advanced = root.querySelector("#settings-advanced-body");
    if (advanced) advanced.innerHTML = advancedHtml(body);
    // A missing required item opens the panel and focuses its input.
    if (messages.google_tiles_key) {
      root.hidden = false;
      const input = root.querySelector("#settings-google_tiles_key");
      if (input) input.focus();
    }
    const toggle = document.getElementById("settingsToggle");
    if (toggle) toggle.textContent = missingKeys.length ? `settings (${missingKeys.length} to fix)` : "settings";
  }

  function fail(text) {
    if (!root) return;
    root.querySelector("#settings-status").textContent = text;
  }

  async function load() {
    try {
      const r = await fetch("/settings");
      const body = await r.json();
      if (!r.ok) { fail(body.detail || ("GET /settings: " + r.status)); return null; }
      render(body);
      return body;
    } catch (e) { fail("settings: server unreachable (" + (e && e.message || e) + ")"); return null; }
  }

  // PUT one row; the reply is the whole GET body, rendered. A refusal
  // (422, settings.<key>: <why>) is shown by name, nothing is reset.
  async function save(key, value) {
    const update = {}; update[key] = value;
    try {
      const r = await fetch("/settings", {method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({settings: update})});
      const body = await r.json();
      if (!r.ok) { fail(body.detail || ("PUT /settings: " + r.status)); return null; }
      render(body);
      fail("saved " + key);
      return body;
    } catch (e) { fail("settings: save failed (" + (e && e.message || e) + ")"); return null; }
  }

  // The fields a user sees: inputs and selects of the panel outside a
  // closed <details> (the advanced fold is not counted).
  function fieldsVisible() {
    if (!root) return 0;
    return Array.from(root.querySelectorAll("input, select"))
      .filter(el => !el.closest("details:not([open])")).length;
  }

  function onChange(ev) {
    const el = ev.target;
    if (!el || !el.name || !el.closest("#settings-fields")) return;
    if (READONLY.indexOf(el.name) >= 0) return;
    save(el.name, el.value);
  }

  function onClick(ev) {
    const btn = ev.target.closest(".settings-show");
    if (!btn) return;
    const input = document.getElementById(btn.dataset.for);
    if (!input) return;
    const shown = input.type === "text";
    input.type = shown ? "password" : "text";
    btn.textContent = shown ? "show" : "hide";
  }

  function mount(el) {
    root = el;
    if (!root.querySelector("#settings-fields")) {
      const div = document.createElement("div"); div.id = "settings-fields";
      root.insertBefore(div, root.firstChild);
    }
    if (!root.querySelector("#settings-status")) {
      const p = document.createElement("p"); p.id = "settings-status"; p.className = "dim";
      root.appendChild(p);
    }
    root.addEventListener("change", onChange);
    root.addEventListener("click", onClick);
    const toggle = document.getElementById("settingsToggle");
    if (toggle) toggle.addEventListener("click", () => { root.hidden = !root.hidden; });
    return load();
  }

  return {mount, render, save, fieldsVisible, messageFor, load,
          FIELDS: FIELDS.slice(), READONLY: READONLY.slice(), SECRETS: SECRETS.slice(),
          MESSAGES: Object.assign({}, MESSAGES), state: () => state};
})();
