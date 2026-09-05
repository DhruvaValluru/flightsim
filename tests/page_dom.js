// A minimal DOM for running the page's glue under node.
//
// tests/test_webapp_capture.py runs the page's PURE HTML builders
// verbatim (the PAGE_CAPTURE block) -- but poll(), renderCapture(),
// initFilesPanel(), initFlightPath(), toggleOverlays(), renderSpec()
// and startRun() touch the document and fetch, and were pinned only by
// regex on the source. This file loads index.html's OWN script over a
// small document (the body's markup parsed into elements that support
// what the page uses: getElementById, innerHTML, textContent,
// querySelector(All) with tag / #id / .class / [attr="value"] and
// descendant selectors, dataset, classList, appendChild,
// insertAdjacentHTML, addEventListener, src/href/value/disabled), with
// fetch answered from a table of routes the test filled from the real
// TestClient payloads, then runs a list of actions and prints a
// snapshot of the document after each. No browser engine, no npm: what
// is asserted is the DOM the page's own code built.
//
// usage: node page_dom.js <input.json>
//   input: {index, routes: {"GET /runs/x": {status, body} | {throw}},
//           actions: [{do: poll|toggleOverlays|renderSpec|editedSpecDict|
//                          setInput|startRun|snapshot, ...}]}
//   output: JSON list, one entry per action.
"use strict";
const fs = require("fs");
const vm = require("vm");

const VOID = new Set(["img", "input", "br", "hr", "meta", "link", "source",
                      "area", "base", "col", "embed", "param", "track", "wbr"]);
const ENTITIES = {quot: '"', lt: "<", gt: ">", nbsp: " ", mdash: "—",
                  middot: "·", ldquo: "“", rdquo: "”",
                  hellip: "…", amp: "&"};

function decode(text) {
  return String(text).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, name) => {
    if (name[0] === "#") {
      return String.fromCodePoint(name[1] === "x" || name[1] === "X"
        ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10));
    }
    return name in ENTITIES ? ENTITIES[name] : m;
  });
}
function escText(t) {
  return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escAttr(t) {
  return String(t).replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

class TextNode {
  constructor(raw) { this.raw = raw; this.nodeType = 3; this.parentElement = null; }
  get textContent() { return decode(this.raw); }
  serialize() { return this.raw; }
}

// -- selectors --------------------------------------------------------

function parseCompound(text) {
  const out = {tag: null, id: null, classes: [], attrs: []};
  let rest = text;
  const tag = rest.match(/^[a-zA-Z][\w-]*/);
  if (tag) { out.tag = tag[0].toUpperCase(); rest = rest.slice(tag[0].length); }
  const token = /^(?:#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\])/;
  while (rest.length) {
    const m = rest.match(token);
    if (!m) throw new Error(`unsupported selector: ${text}`);
    if (m[1] !== undefined) out.id = m[1];
    else if (m[2] !== undefined) out.classes.push(m[2]);
    else out.attrs.push({name: m[3], value: m[4] ?? m[5] ?? m[6] ?? null});
    rest = rest.slice(m[0].length);
  }
  return out;
}

function matchesCompound(el, c) {
  if (c.tag && el.tagName !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  const classes = el.className.split(/\s+/);
  for (const cls of c.classes) if (!classes.includes(cls)) return false;
  for (const a of c.attrs) {
    if (!el.hasAttribute(a.name)) return false;
    if (a.value !== null && el.getAttribute(a.name) !== a.value) return false;
  }
  return true;
}

function matchesChain(el, parts, index) {
  if (!matchesCompound(el, parts[index])) return false;
  if (index === 0) return true;
  for (let a = el.parentElement; a; a = a.parentElement) {
    if (matchesChain(a, parts, index - 1)) return true;
  }
  return false;
}

function matches(el, selector) {
  return selector.split(",").some(one => {
    const parts = one.trim().split(/\s+/).map(parseCompound);
    return matchesChain(el, parts, parts.length - 1);
  });
}

// -- elements ---------------------------------------------------------

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.nodeType = 1;
    this.attrs = new Map();
    this.children = [];
    this.parentElement = null;
    this.style = {};
    this.listeners = {};
    this.props = {};
  }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  removeAttribute(name) { this.attrs.delete(name); }
  hasAttribute(name) { return this.attrs.has(name); }
  get id() { return this.getAttribute("id") || ""; }
  set id(v) { this.setAttribute("id", v); }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get classList() {
    const el = this;
    return {
      contains: c => el.className.split(/\s+/).includes(c),
      add(c) { if (!this.contains(c)) el.className = (el.className + " " + c).trim(); },
      remove(c) { el.className = el.className.split(/\s+/).filter(x => x && x !== c).join(" "); },
      toggle(c, force) {
        const on = force === undefined ? !this.contains(c) : !!force;
        if (on) this.add(c); else this.remove(c);
        return on;
      },
    };
  }
  get dataset() {
    const out = {};
    for (const [k, v] of this.attrs) {
      if (k.startsWith("data-")) {
        out[k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = v;
      }
    }
    return out;
  }
  get src() { return this.getAttribute("src") || ""; }
  set src(v) { this.setAttribute("src", v); }
  get href() { return this.getAttribute("href") || ""; }
  set href(v) { this.setAttribute("href", v); }
  get title() { return this.getAttribute("title") || ""; }
  set title(v) { this.setAttribute("title", v); }
  get placeholder() { return this.getAttribute("placeholder") || ""; }
  set placeholder(v) { this.setAttribute("placeholder", v); }
  get disabled() {
    return "disabled" in this.props ? this.props.disabled : this.hasAttribute("disabled");
  }
  set disabled(v) {
    this.props.disabled = !!v;
    if (v) this.setAttribute("disabled", ""); else this.removeAttribute("disabled");
  }
  get checked() { return !!this.props.checked; }
  set checked(v) { this.props.checked = !!v; }
  get options() { return this.children.filter(c => c.tagName === "OPTION"); }
  get value() {
    if ("value" in this.props) return this.props.value;
    if (this.tagName === "SELECT") {
      const options = this.options;
      const picked = options.find(o => o.hasAttribute("selected")) || options[0];
      return picked ? picked.value : "";
    }
    return this.getAttribute("value") ?? "";
  }
  set value(v) { this.props.value = String(v); }
  get textContent() {
    return this.children.map(c => c.textContent).join("");
  }
  set textContent(v) {
    this.children = [];
    this.appendChild(new TextNode(escText(String(v))));
  }
  get innerHTML() { return this.children.map(c => c.serialize()).join(""); }
  set innerHTML(html) {
    this.children = [];
    for (const node of parseHtml(String(html))) this.appendChild(node);
  }
  appendChild(node) { node.parentElement = this; this.children.push(node); return node; }
  insertAdjacentHTML(position, html) {
    const nodes = parseHtml(String(html));
    if (position === "beforeend") nodes.forEach(n => this.appendChild(n));
    else if (position === "afterbegin") {
      nodes.forEach(n => { n.parentElement = this; });
      this.children = nodes.concat(this.children);
    } else throw new Error(`insertAdjacentHTML ${position} unsupported`);
  }
  *descendants() {
    for (const child of this.children) {
      if (child.nodeType !== 1) continue;
      yield child;
      yield* child.descendants();
    }
  }
  querySelectorAll(selector) {
    return Array.from(this.descendants()).filter(el => matches(el, selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let el = this; el; el = el.parentElement) if (matches(el, selector)) return el;
    return null;
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatchEvent(event) {
    (this.listeners[event.type] || []).forEach(fn => fn.call(this, event));
    return true;
  }
  getContext() {
    // A canvas that accepts every call and every property and draws
    // nothing: the chart's arithmetic runs, its pixels are not judged.
    return new Proxy({}, {get: (t, k) => (k in t ? t[k] : () => undefined),
                          set: (t, k, v) => { t[k] = v; return true; }});
  }
  serialize() {
    const attrs = Array.from(this.attrs).map(([k, v]) =>
      v === "" ? ` ${k}` : ` ${k}="${escAttr(v)}"`).join("");
    const tag = this.tagName.toLowerCase();
    if (VOID.has(tag)) return `<${tag}${attrs}>`;
    return `<${tag}${attrs}>${this.innerHTML}</${tag}>`;
  }
}

// -- parser -----------------------------------------------------------

function parseHtml(html) {
  const root = new Element("#root");
  const stack = [root];
  const tokens = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s=\/>]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>|([^<]+|<)/g;
  const attrRe = /([^\s=\/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let m;
  while ((m = tokens.exec(html)) !== null) {
    if (m[0].startsWith("<!--")) continue;
    const top = stack[stack.length - 1];
    if (m[1] !== undefined) {
      const name = m[1].toUpperCase();
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === name) { stack.length = i; break; }
      }
    } else if (m[2] !== undefined) {
      const el = new Element(m[2]);
      let a;
      attrRe.lastIndex = 0;
      while ((a = attrRe.exec(m[3] || "")) !== null) {
        el.setAttribute(a[1], decode(a[2] ?? a[3] ?? a[4] ?? ""));
      }
      top.appendChild(el);
      if (!VOID.has(m[2].toLowerCase()) && !m[4]) stack.push(el);
    } else {
      top.appendChild(new TextNode(m[5]));
    }
  }
  return root.children.map(n => { n.parentElement = null; return n; });
}

// -- the document and the page --------------------------------------------

function makeDocument(bodyHtml) {
  const body = new Element("body");
  body.innerHTML = bodyHtml;
  const document = {
    body,
    getElementById(id) {
      for (const el of body.descendants()) if (el.id === id) return el;
      return null;
    },
    querySelectorAll: selector => body.querySelectorAll(selector),
    querySelector: selector => body.querySelector(selector),
    createElement: tag => new Element(tag),
  };
  return document;
}

async function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const html = fs.readFileSync(input.index, "utf8");
  const bodyStart = html.indexOf("<body>") + "<body>".length;
  const scriptStart = html.indexOf("<script>");
  const bodyHtml = html.slice(bodyStart, scriptStart);
  const script = html.slice(scriptStart + "<script>".length,
                            html.lastIndexOf("</script>"));
  const document = makeDocument(bodyHtml);
  const routes = input.routes || {};
  const fetches = [];
  const timeouts = [];
  async function fetch(url, options) {
    const method = (options && options.method) || "GET";
    const key = `${method} ${url}`;
    fetches.push(key);
    const route = routes[key];
    if (!route) return {ok: false, status: 404, json: async () => ({error: "no route"})};
    if (route.throw) throw new TypeError(`fetch failed: ${key}`);
    const status = route.status ?? 200;
    return {ok: status >= 200 && status < 300, status,
            json: async () => route.body};
  }
  const context = vm.createContext({
    document, fetch, console,
    localStorage: {getItem: () => null, setItem() {}},
    setTimeout: (fn, ms) => { timeouts.push(ms); },
    requestAnimationFrame: () => {},
  });
  const tail = `
;globalThis.__page = {
  poll, toggleOverlays, renderSpec, renderVerdict, editedSpecDict, startRun,
  get activeRun() { return activeRun; }, set activeRun(v) { activeRun = v; },
};`;
  vm.runInContext(script + tail, context, {filename: "index.html"});
  const page = context.__page;
  const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };
  await settle();

  const byId = id => document.getElementById(id);
  const inner = id => { const el = byId(id); return el ? el.innerHTML : null; };
  const text = id => { const el = byId(id); return el ? el.textContent : null; };
  function snapshot() {
    return {
      status: text("status"), statusHtml: inner("status"),
      runAreaDisplay: byId("runArea").style.display ?? null,
      clipArea: inner("clipArea"), captureArea: inner("captureArea"),
      captureDownloads: inner("captureDownloads"),
      captureGalleries: inner("captureGalleries"),
      filesArea: inner("filesArea"), pathArea: inner("pathArea"),
      aeroSide: inner("aeroSide"), specTable: inner("specTable"),
      verdict: inner("verdict"), runDisabled: byId("run").disabled,
      renderNote: text("renderNote"), llmState: text("llmState"),
      frames: document.querySelectorAll('.thumbs[data-kind="frames"] img').map(img => ({
        camera: img.closest("[data-camera]").getAttribute("data-camera"),
        src: img.src, href: img.parentElement.href})),
      timeouts: timeouts.slice(), fetches: fetches.slice(),
    };
  }

  const out = [];
  for (const action of input.actions || []) {
    if (action.do === "poll") {
      page.activeRun = action.runId;
      byId("runArea").style.display = "";
      await page.poll();
      await settle();
      out.push(snapshot());
    } else if (action.do === "toggleOverlays") {
      page.toggleOverlays(action.camera, action.on);
      out.push(snapshot());
    } else if (action.do === "renderSpec") {
      page.renderSpec(action.payload);
      out.push(snapshot());
    } else if (action.do === "renderVerdict") {
      page.renderVerdict(action.payload);
      out.push(snapshot());
    } else if (action.do === "editedSpecDict") {
      out.push({dict: page.editedSpecDict()});
    } else if (action.do === "setInput") {
      const input = document.querySelector(`#specTable input[data-name="${action.name}"]`);
      if (!input) throw new Error(`no input ${action.name}`);
      input.value = action.value;
      input.dispatchEvent({type: "change"});
      const srcKey = input.dataset.srcKey || action.name;
      out.push(Object.assign(snapshot(), {
        sourceCell: document.querySelector(`[data-src="${srcKey}"]`).serialize(),
        sourceCells: document.querySelectorAll(`[data-src="${srcKey}"]`).map(c => c.serialize())}));
    } else if (action.do === "startRun") {
      await page.startRun(action.mayBake ?? false, action.endpoint || "/run");
      await settle();
      out.push(snapshot());
    } else if (action.do === "snapshot") {
      out.push(snapshot());
    } else {
      throw new Error(`unknown action ${action.do}`);
    }
  }
  process.stdout.write(JSON.stringify(out));
}

main().catch(error => { console.error(error.stack || String(error)); process.exit(1); });
