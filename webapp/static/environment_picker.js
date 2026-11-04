// The environment picker (Phase 3 D4): a two-option preset over the
// scene-setting rule. Picking "Desert" or "Forest" does NOT edit the prompt
// text (the conditions list does that): it sends a structured
// ``environment`` field with POST /compile, which the server applies as a
// USER edit of surface, place, sun and season before the scene-setting
// planner runs (webapp/runs.py ENVIRONMENT_PRESETS). The review table then
// shows every one of those fields with "environment preset (web UI)" as
// its provenance. The first option is "none": today's behaviour, the
// prompt (or its absence) decides the scene.
(function () {
"use strict";

// [value sent to /compile, label]. The server's ENVIRONMENT_PRESETS keys
// are the only accepted values; an unknown one is refused by name (400).
const PRESETS = [
  ["", "none (the prompt decides)"],
  ["desert", "Desert (Grand Canyon, July noon)"],
  ["forest", "Forest (Yosemite, June morning)"],
];

const STYLE = `
.envPicker { margin: 0.4em 0; }
.envPicker label { font-size: 0.95em; }
.envPicker select { margin-left: 0.4em; }
.envPicker .envHint { opacity: 0.7; margin-left: 0.6em; font-size: 0.9em; }
`;

let select = null;

// The preset to send: null for "none" (the field is then left out of the
// request's meaning: absent/None = today's behaviour).
function value() {
  if (!select) return null;
  const v = select.value;
  return v === "" ? null : v;
}

function mount(container, hooks) {
  hooks = hooks || {};
  if (!document.getElementById("envPickerStyle")) {
    const style = document.createElement("style");
    style.id = "envPickerStyle";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }
  container.classList.add("envPicker");
  container.innerHTML = "";
  const label = document.createElement("label");
  label.textContent = "environment";
  label.title = "A preset fixes the place, surface, sun and season as user "
    + "edits (shown in the table). Google tiles stay the ground. "
    + "\"none\" leaves the scene to the prompt.";
  select = document.createElement("select");
  select.id = "environmentPreset";
  for (const [preset, text] of PRESETS) {
    const option = document.createElement("option");
    option.value = preset;
    option.textContent = text;
    select.appendChild(option);
  }
  select.addEventListener("change", () => {
    if (typeof hooks.onChange === "function") hooks.onChange(value());
  });
  label.appendChild(select);
  container.appendChild(label);
  const hint = document.createElement("span");
  hint.className = "envHint";
  hint.textContent = "desert -> Grand Canyon, forest -> Yosemite";
  container.appendChild(hint);
  return {value: value, select: select};
}

window.EnvironmentPicker = {mount: mount, value: value, PRESETS: PRESETS};
})();
