"""The agentic controller with stated authority (Phase 2, package H;
contracts §7, brainstorm §7).

Three layers, each usable without a model:

* :mod:`core.agent.tools` -- the typed tools (``compile``, ``validate``,
  ``plan_campaign``, ``sample``, ``run``, ``render``, ``verify``,
  ``export``, ``inspect``, ``report``) with JSON schemas drawn from
  their signatures; each a thin call into the library that already
  exists (the compilers, the campaign, the verifier, the overlay).
* :mod:`core.agent.policy` -- the deterministic authority checks:
  stated fields are immutable, ``run``/``render``/``export`` need the
  validation token ``validate()`` minted for that spec digest, a spec
  carrying a refusal is not run, and budgets end the loop. Every
  denial is BY NAME (``authority.*`` in the catalogue).
* :mod:`core.agent.controller` -- the loop: plan from the request,
  call tools, read results, re-sample only system-chosen fields,
  verify the yield, escalate in one plain sentence.

Every call is a line of ``trace.jsonl`` beside the campaign
(:mod:`core.agent.trace`).

    from core.agent import Tools, Controller, Request
    tools = Tools(out="campaigns/demo")
    outcome = Controller(tools).run(Request("fly the a320 at 3000 m in varied weather", images=200))
"""

from .controller import Controller, Outcome, Request  # noqa: F401
from .policy import Budget, Denial, Policy  # noqa: F401
from .tools import TOOL_NAMES, Tools, mint_token, schemas  # noqa: F401
from .trace import Trace  # noqa: F401
