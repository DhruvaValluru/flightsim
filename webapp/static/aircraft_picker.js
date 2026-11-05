// The aircraft picker (box P1): the page's "pick aircraft" step. Filled from
// GET /aircraft with the default run's aircraft selected. value() stays null
// until a person changes the select, so an untouched picker sends nothing: an
// aircraft named in the prompt still decides, and Capture still posts {}.
(function () {
"use strict";

const STYLE = `
.aircraftPicker { margin: 0.4em 0; }
.aircraftPicker label { font-size: 0.95em; }
.aircraftPicker select { margin-left: 0.4em; }
.aircraftPicker .aircraftHint { opacity: 0.7; margin-left: 0.6em; font-size: 0.9em; }
`;

let select = null;
let picked = false;

function value() {
  return select && picked ? select.value : null;
}

function mount(container, hooks) {
  hooks = hooks || {};
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);
  container.classList.add("aircraftPicker");
  container.innerHTML = "";
  const label = document.createElement("label");
  label.textContent = "aircraft";
  label.title = "The aircraft this run flies, at its own usual speed. "
    + "Picking one wins over an aircraft named in the prompt.";
  select = document.createElement("select");
  select.id = "aircraftPreset";
  select.disabled = true;
  select.addEventListener("change", () => {
    picked = true;
    if (typeof hooks.onChange === "function") hooks.onChange(select.value);
  });
  label.appendChild(select);
  container.appendChild(label);
  const hint = document.createElement("span");
  hint.className = "aircraftHint";
  container.appendChild(hint);
  fetch("/aircraft").then(response => response.json()).then(data => {
    for (const entry of data.aircraft) {
      const option = document.createElement("option");
      option.value = entry.name;
      option.textContent = entry.title;
      option.selected = entry.name === data.default;
      select.appendChild(option);
    }
    select.disabled = false;
  }).catch(() => {
    hint.textContent = "the aircraft list did not load; the prompt decides";
  });
  return {value: value, select: select};
}

window.AircraftPicker = {mount: mount, value: value};
})();
