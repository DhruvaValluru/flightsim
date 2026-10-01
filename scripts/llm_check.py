"""Say why the language-model tier does or does not compile a prompt.

The web app falls back to the offline parser silently when the model is
unreachable or answers badly; this prints the real reason, tier by tier.

    .venv\\Scripts\\python.exe scripts\\llm_check.py ["your prompt"]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.providers import resolve_client  # noqa: E402

PROMPT = ("Fly the A-4 Skyhawk past the Matterhorn at 5200 m and 350 knots, "
          "heading east, at sunset, for 30 seconds, chase camera.")


def ping(tier: str) -> bool:
    os.environ["FLIGHTSIM_LLM"] = tier
    try:
        client, model = resolve_client()
    except Exception as exc:            # misconfiguration, named
        print(f"[{tier}] not configured: {exc}")
        return False
    print(f"[{tier}] endpoint {getattr(client, 'base_url', '?')}  model {model}")
    try:
        reply = client.messages.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the word ok."}])
        print(f"[{tier}] reachable; it answered: {reply.content[0].text!r}")
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:600]
        print(f"[{tier}] HTTP {exc.code} {exc.reason}: {body}")
    except Exception as exc:
        print(f"[{tier}] FAILED: {type(exc).__name__}: {exc}")
    return False


def compile_with(tier: str, prompt: str) -> None:
    from core.nl.llm_compiler import compile_prompt_llm

    os.environ["FLIGHTSIM_LLM"] = tier
    try:
        spec = compile_prompt_llm(prompt).spec
    except Exception as exc:
        cause = exc.__cause__ or exc.__context__
        print(f"[{tier}] compile FAILED: {exc}"
              + (f"\n    cause: {type(cause).__name__}: {cause}" if cause else ""))
        return
    print(f"[{tier}] compiled: aircraft {spec.aircraft.value}, lat "
          f"{spec.latitude.value}, lon {spec.longitude.value}, heading "
          f"{spec.heading.value}, time {spec.time_of_day.value}")
    if spec.notes:
        print("    notes: " + json.dumps(spec.notes))


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else PROMPT
    configured = os.environ.get("FLIGHTSIM_LLM", "").strip() or (
        "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "relay")
    print(f"configured tier: {configured}\n")
    for tier in ("relay", "llm7"):
        if ping(tier):
            compile_with(tier, prompt)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
