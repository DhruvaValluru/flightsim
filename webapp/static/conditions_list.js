// The conditions list: a quick, clickable list beside the prompt box of the
// weather and environments this build can actually fly. Clicking a phrase
// adds it to the prompt. Every phrase in GROUPS is one the offline compiler
// (core/nl/compiler.py) turns into a stated spec field -- pinned by
// tests/test_conditions_list.py, so the list cannot advertise a condition
// that would be silently dropped. TABLE_ONLY names what the spec carries
// but the prompt cannot set: those are set in the review table after
// Interpret (or in the scenario file), and are not clickable.
(function () {
"use strict";

const GROUPS = [
  {title: "Wind", items: [
    ["light wind", "in a light wind"],
    ["breezy", "in a breezy wind"],
    ["moderate wind", "in a moderate wind"],
    ["gusty wind", "in a gusty wind"],
    ["strong wind", "in a strong wind"],
    ["gale force", "in gale force winds"],
    ["headwind", "with a headwind"],
    ["tailwind", "with a tailwind"],
    ["crosswind", "with a crosswind"],
    ["strong crosswind", "with a strong crosswind"],
  ]},
  {title: "Turbulence", items: [
    ["choppy", "in choppy air"],
    ["light", "in light turbulence"],
    ["moderate", "in moderate turbulence"],
    ["severe", "in severe turbulence"],
  ]},
  {title: "Storms", items: [
    ["past a thunderstorm", "past a thunderstorm"],
    ["through a thunderstorm", "through a thunderstorm"],
    ["near a tornado", "near a tornado"],
    ["through a tornado", "through a tornado"],
  ]},
  {title: "Time of day", items: [
    ["dawn", "at dawn"],
    ["sunrise", "at sunrise"],
    ["morning", "in the morning"],
    ["noon", "at noon"],
    ["afternoon", "in the afternoon"],
    ["golden hour", "at golden hour"],
    ["sunset", "at sunset"],
    ["dusk", "at dusk"],
    ["twilight", "at twilight"],
    ["night", "at night"],
    ["a clock time", "at 6:30 pm"],
  ]},
  {title: "Ground below", items: [
    ["grassland", "over grassland"],
    ["desert", "over the desert"],
    ["ocean", "over the ocean"],
    ["forest", "over a forest"],
    ["city", "over the city"],
  ]},
  {title: "Real places (real terrain)", items: [
    ["Matterhorn", "over the Matterhorn"],
    ["Yosemite", "over Yosemite"],
    ["Mount Fuji", "over Mount Fuji"],
    ["Mount Everest", "over Mount Everest"],
    ["Grand Canyon", "over the Grand Canyon"],
    ["Flint Hills, Kansas", "over the Flint Hills"],
  ]},
  {title: "Real weather on a date", items: [
    ["that day's wind (ERA5)", "on 2024-07-15"],
  ]},
  {title: "Varied (for many images)", items: [
    ["varied weather", "in varied weather"],
    ["times of day", "at different times of day"],
    ["dawn and dusk", "at dawn and dusk"],
    ["varied lighting", "with varied lighting"],
    ["all four seasons", "in all four seasons"],
  ]},
];

const TABLE_ONLY = [
  ["rain", "the precipitation rate row (mm/h) in the table after Interpret"],
  ["rain on the aircraft, wet or flooded runway", "the rain block in the scenario file (needs a rain rate)"],
  ["fog / haze", "varied weather, or the fog density row in the table"],
  ["icing", "the icing block in the scenario file"],
];

const STYLE = `
.condList { font-size: .82rem; line-height: 1.35; }
.condList h4 { margin: 0 0 .35rem; font-size: .85rem; font-weight: 600; opacity: .85; }
.condList details { margin: 0 0 .35rem; }
.condList summary { cursor: pointer; opacity: .8; }
.condList .chips { display: flex; flex-wrap: wrap; gap: .25rem; margin: .3rem 0 .2rem; }
.condList button.chip { font: inherit; font-size: .8rem; padding: .12rem .5rem; border-radius: 999px;
  background: transparent; color: inherit; border: 1px solid rgba(127,140,150,.45); cursor: pointer; }
.condList button.chip:hover { border-color: rgba(127,180,220,.9); }
.condList ul { margin: .25rem 0 0 1rem; padding: 0; opacity: .75; }
`;

function addPhrase(textarea, phrase) {
  const text = textarea.value;
  if (text.toLowerCase().includes(phrase.toLowerCase())) { textarea.focus(); return; }
  textarea.value = text.trim() ? `${text.replace(/\s+$/, "")} ${phrase}` : phrase;
  textarea.dispatchEvent(new Event("input", {bubbles: true}));
  textarea.focus();
}

function mount(container, textarea) {
  if (!document.getElementById("condListStyle")) {
    const style = document.createElement("style");
    style.id = "condListStyle";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }
  container.classList.add("condList");
  container.innerHTML = "";
  const head = document.createElement("h4");
  head.textContent = "Conditions you can ask for (click to add)";
  container.appendChild(head);
  GROUPS.forEach((group, index) => {
    const details = document.createElement("details");
    if (index < 3) details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = group.title;
    details.appendChild(summary);
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const [label, phrase] of group.items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = label;
      button.title = `adds "${phrase}"`;
      button.addEventListener("click", () => addPhrase(textarea, phrase));
      chips.appendChild(button);
    }
    details.appendChild(chips);
    container.appendChild(details);
  });
  const later = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Not from the prompt yet";
  later.appendChild(summary);
  const list = document.createElement("ul");
  for (const [what, where] of TABLE_ONLY) {
    const item = document.createElement("li");
    item.textContent = `${what}: ${where}`;
    list.appendChild(item);
  }
  later.appendChild(list);
  container.appendChild(later);
}

window.ConditionsList = {mount, GROUPS, TABLE_ONLY};
})();
