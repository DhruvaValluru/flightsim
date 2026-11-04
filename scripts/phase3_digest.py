#!/usr/bin/env python3
"""Write docs/phase3/digest_<L>.md for the Phase 3 breakdown stage.

  python3 scripts/phase3_digest.py A            # every box of letter A
  python3 scripts/phase3_digest.py A C1 C5 C6   # letter A plus named boxes

For each box: the plan section from tasks/phase3_todo.md verbatim, the files
it names (resolved against the tree, marked exists / new / missing), and the
signatures in the existing files (grep for def/class and the language's
equivalent), never file bodies. Capped at 120 lines per box; the plan text is
never cut, the signature list is.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "tasks" / "phase3_todo.md"
CAP = 120

SIG = {
    ".py": r"^def |^class |^    def |^async def |^    async def ",
    ".ps1": r"^function |^param\(",
    ".sh": r"^[a-zA-Z_][a-zA-Z0-9_]*\(\) *\{|^function ",
    ".cpp": r"^[A-Za-z_][A-Za-z0-9_:<>*&, ]*\b[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_~][A-Za-z0-9_]*\(",
    ".h": r"^\s*(class|struct) [A-Z]|^\s*UFUNCTION|^\s*(virtual |static )?[A-Za-z_][A-Za-z0-9_<>*&:]* [A-Za-z_][A-Za-z0-9_]*\(.*\)( const| override)?;",
    ".cs": r"^\s*(public|private|protected|internal) |^\s*class ",
    ".yaml": r"^[A-Za-z_][A-Za-z0-9_.-]*:",
    ".yml": r"^[A-Za-z_][A-Za-z0-9_.-]*:",
    ".js": r"^\s*(async )?function |^\s*(const|let|var) [A-Za-z_$][A-Za-z0-9_$]* = (async )?(\(|function)",
    ".html": r"<script|^\s*(async )?function |^\s*(const|let|var) [A-Za-z_$][A-Za-z0-9_$]* = (async )?(\(|function)|id=\"[a-z]",
    ".ini": r"^\[|^[A-Za-z]",
    ".json": r"^  \"[A-Za-z_]",
    ".md": r"^#",
    ".xml": r"^\s*<(metrics|mass_balance|pointmass|aerodynamics|propulsion|ground_reactions|flight_control|system|channel)\b",
    ".cmd": r"^:|^call |^powershell",
}


def sections() -> dict[str, str]:
    text = PLAN.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^### ([A-F]\d+) ", line)
        if m or line.startswith("**[CHECKPOINT]") or line.startswith("## "):
            if cur:
                out[cur] = "\n".join(buf).rstrip() + "\n"
            cur = m.group(1) if m else None
            buf = [line] if m else []
            continue
        if cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).rstrip() + "\n"
    return out


def files_of(section: str) -> list[str]:
    m = re.search(r"- \*\*Files:\*\*(.*?)(?=\n- \*\*|\n\n|\Z)", section, re.S)
    if not m:
        return []
    names = re.findall(r"`([^`]+)`", m.group(1))
    out = []
    for n in names:
        n = n.strip()
        if "/" not in n and "." not in n:
            continue
        if n.endswith("/"):
            n = n.rstrip("/")
        if n not in out:
            out.append(n)
    return out


def resolve(name: str, section: str) -> tuple[str, str]:
    p = ROOT / name
    if p.exists():
        return name, "exists"
    if "/" not in name:
        hits = [h for h in subprocess.run(
            ["find", ".", "-name", name, "-not", "-path", "./.venv/*", "-not", "-path", "./.git/*"],
            cwd=ROOT, capture_output=True, text=True).stdout.split("\n") if h]
        if len(hits) == 1:
            return hits[0][2:], "exists"
        if hits:
            return name, "ambiguous: " + ", ".join(h[2:] for h in hits)
    if re.search(re.escape(name) + r"[^\n]*\(new", section):
        return name, "new"
    return name, "missing"


def signatures(path: str) -> list[str]:
    pat = SIG.get(Path(path).suffix)
    if not pat:
        return []
    r = subprocess.run(["grep", "-nE", pat, path], cwd=ROOT, capture_output=True, text=True)
    return [l.rstrip() for l in r.stdout.split("\n") if l.strip()]


def digest(box: str, section: str) -> str:
    lines = [f"## {box}", "", "### plan (verbatim)", ""]
    lines += section.rstrip().split("\n")
    lines += ["", "### files"]
    resolved = []
    for name in files_of(section):
        path, status = resolve(name, section)
        resolved.append((path, status))
        extra = f" -> {path}" if path != name else ""
        lines.append(f"- `{name}`{extra} [{status}]")
    existing = [p for p, s in resolved if s == "exists" and (ROOT / p).is_file()]
    budget = max(CAP - len(lines) - 2, 10)
    sig_lines: list[str] = []
    per_file = max(budget // max(len(existing), 1), 3)
    for p in existing:
        sigs = signatures(p)
        shown = sigs[:per_file]
        sig_lines.append(f"- `{p}` ({len(sigs)} signatures{', first ' + str(len(shown)) + ' shown' if len(shown) < len(sigs) else ''})")
        sig_lines += [f"    {s}" for s in shown]
    lines += ["", "### signatures"] + (sig_lines or ["(no existing source files)"])
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    letter = argv[0]
    secs = sections()
    boxes = [b for b in secs if b[0] == letter] + [b for b in argv[1:] if b in secs and b[0] != letter]
    missing = [b for b in argv[1:] if b not in secs]
    if missing:
        print("not in plan:", missing, file=sys.stderr)
        return 1
    out = ROOT / "docs" / "phase3" / f"digest_{letter}.md"
    parts = [f"# Digest {letter}", "", f"Plan: tasks/phase3_todo.md · boxes: {', '.join(boxes)}", ""]
    for b in boxes:
        parts.append(digest(b, secs[b]))
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}: {len(boxes)} boxes, {sum(1 for _ in out.read_text(encoding="utf-8").splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
