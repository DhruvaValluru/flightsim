"""Campaign execution at scale (Phase 2, package G; contracts §6).

A campaign is a prompt, a target number of images and a seed, run as
many content-addressed cases through the existing headless pipeline
(``flightsim.capture`` -> verify) by a pool of workers that pull
cases BY INDEX. Every draw is seeded from ``SeedSequence([index,
campaign_seed])`` so the case set is a property of the design, not of
the worker count; progress and yield are computed from the ledger,
so a restarted process reports the truth; a campaign never reports
``done`` below its target.

    from core.campaign import Campaign
    c = Campaign.create("fly the a320 at 3000 m in varied weather",
                        images=500, seed=7, out="campaigns/demo")
    c.plan(); c.run(workers=2); c.report(); c.export("coco")
"""

from .campaign import (  # noqa: F401
    STATES, TRANSITIONS, Campaign, CampaignError,
)
from .ledger import Ledger  # noqa: F401
