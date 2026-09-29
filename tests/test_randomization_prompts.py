"""Phase 2, package F: the randomisation vocabulary measured on a corpus
(contracts §5.3), the tests/test_camera_prompts.py pattern.

Every documented phrase family maps to its policy leaves with the
quoted phrase as attribution (source inferred); a sentence asking to
vary something the vocabulary lacks is refused BY NAME
(``randomization.vocabulary``) by the sampler, quoting the sentence;
a prompt with no variation language compiles exactly as before. The
corpus is scored as a whole and must score 100 %.
"""

import pytest

from core.nl.compiler import (
    RANDOMIZATION_FAMILIES, VARIATION_INTENT, compile_prompt,
)
from core.scenario.fields import Source
from core.scenario.randomization import RandomizationError, sample_randomization

# (prompt, expected) -- expected keys: leaves (the policy's leaf names,
# sorted), unmapped (sentences the sampler refuses), cameras (ids),
# attribution {leaf: phrase}, notes (substring that must appear).
CORPUS = [
    ("fly the 747 at 3000 m and 250 kt",
     {"leaves": None}),
    ("fly the 747 in moderate turbulence with a strong crosswind",
     {"leaves": None}),
    ("fly the 747 at 3000 m in varied weather",
     {"leaves": ["cloud_cover", "precipitation", "visibility_km"],
      "attribution": {"cloud_cover": "varied weather"}}),
    ("random weather conditions for the a320 at 5000 m",
     {"leaves": ["cloud_cover", "precipitation", "visibility_km"]}),
    ("fly the cessna at different times of day",
     {"leaves": ["hour_local"], "attribution": {"hour_local": "different times of day"}}),
    ("fly the cessna at random times of the day",
     {"leaves": ["hour_local"]}),
    ("images of the 747 at all hours",
     {"leaves": ["hour_local"]}),
    ("fly the 747, dawn and dusk only",
     {"leaves": ["hour_local"], "attribution": {"hour_local": "dawn and dusk only"},
      "window": True}),
    ("varied lighting on the a320 at 4000 m",
     {"leaves": ["hour_local", "weather_date"],
      "attribution": {"weather_date": "varied lighting"}}),
    ("varied lighting on 2024-01-15 for the a320",
     {"leaves": ["hour_local"], "notes": "weather_date is stated"}),
    ("fly the 747 across the rockies",
     {"leaves": ["location"], "attribution": {"location": "across the rockies"},
      "refused": "randomization.location"}),
    ("fly the cessna over the alps at 4000 m",
     {"leaves": ["location"], "attribution": {"location": "over the alps"}}),
    ("fly the 747 through the himalayas",
     {"leaves": ["location"]}),          # a defaulted altitude follows the ground
    ("fly the 747 over the alps at 46 n 7.7 e",
     {"leaves": ["location"]}),           # coordinates are not a vocabulary word: sampled
    ("fly the 747 with mixed traffic",
     {"leaves": ["traffic_count"], "attribution": {"traffic_count": "mixed traffic"}}),
    ("fly the a320 with other traffic around",
     {"leaves": ["traffic_count"]}),
    ("random viewpoints of the 747 at 3000 m",
     {"leaves": ["cameras"], "cameras": ["chase"],
      "attribution": {"cameras": "random viewpoints"}}),
    ("chase view of the 747 with varied camera angles",
     {"leaves": ["cameras"], "cameras": ["chase"]}),
    ("from the tower and wingman views of the a320 from different viewpoints",
     {"leaves": ["cameras"], "cameras": ["tower", "wingman"]}),
    ("varied weather over the rockies with mixed traffic and random viewpoints "
     "at different times of day",
     {"leaves": ["cameras", "cloud_cover", "hour_local", "location",
                 "precipitation", "traffic_count", "visibility_km"],
      "cameras": ["chase"], "refused": "randomization.location"}),
    ("fly the 747 and vary the moon phase",
     {"leaves": [], "unmapped": ["fly the 747 and vary the moon phase"]}),
    ("fly the 747 in varied weather. randomise the paint scheme",
     {"leaves": ["cloud_cover", "precipitation", "visibility_km"],
      "unmapped": ["randomise the paint scheme"]}),
    ("a variety of aircraft over yosemite",
     {"leaves": [], "unmapped": ["a variety of aircraft over yosemite"]}),
    ("fly the 747 at various altitudes",
     {"leaves": [], "unmapped": ["fly the 747 at various altitudes"]}),
    ("fly the 747 in varied weather, dawn and dusk only",
     {"leaves": ["cloud_cover", "hour_local", "precipitation", "visibility_km"]}),
    ("a different aircraft, the a320, at 3000 m",
     {"leaves": None}),                    # "different" alone is not intent
    ("fly the 747 through mixed cloud at 3000 m",
     {"leaves": None}),                    # "mixed" alone is not intent
]


def _score(prompt, expected):
    spec = compile_prompt(prompt)
    problems = []
    policy = spec.randomization_policy
    if expected["leaves"] is None:
        if policy is not None:
            problems.append(f"policy {sorted(policy.value)} written for a prompt "
                            f"with no variation language")
        if spec.randomization.is_enabled():
            problems.append("the block was switched on")
        return problems
    if policy is None:
        return [f"no policy written; expected leaves {expected['leaves']}"]
    leaves = sorted(policy.value)
    if leaves != expected["leaves"]:
        problems.append(f"leaves {leaves} != {expected['leaves']}")
    if policy.source is not Source.INFERRED:
        problems.append(f"policy source {policy.source} is not inferred")
    for leaf, phrase in expected.get("attribution", {}).items():
        got = policy.detail.get("attribution", {}).get(leaf)
        if got != phrase:
            problems.append(f"{leaf} attributed to {got!r}, expected {phrase!r}")
    for leaf in leaves:
        if leaf not in policy.detail.get("attribution", {}):
            problems.append(f"{leaf} carries no attribution")
        if leaf not in ("cameras", "location") \
                and policy.value[leaf] not in _family_leaves(leaf):
            problems.append(f"{leaf} is not a family's documented distribution")
    unmapped = policy.detail.get("unmapped", [])
    if unmapped != expected.get("unmapped", []):
        problems.append(f"unmapped {unmapped} != {expected.get('unmapped', [])}")
    if expected["leaves"] and not spec.randomization.is_enabled():
        problems.append("the block was not switched on")
    if expected["leaves"] and spec.randomization.enabled.source is not Source.INFERRED:
        problems.append("the switch is not attributed to the phrase")
    if "cameras" in expected:
        ids = [str(c.camera_id.value) for c in spec.cameras]
        if ids != expected["cameras"]:
            problems.append(f"cameras {ids} != {expected['cameras']}")
    if "notes" in expected and not any(expected["notes"] in n for n in spec.notes):
        problems.append(f"no note containing {expected['notes']!r}: {spec.notes}")
    if expected.get("window") and policy.value["hour_local"] != {"choice": ["dawn", "dusk"]}:
        problems.append("dawn/dusk is not the window choice")
    # What the sampler does with it: an unmapped sentence refuses by name
    # quoting it; a range with no bake refuses randomization.location;
    # everything else draws.
    try:
        sample_randomization(spec)
        if unmapped or "refused" in expected:
            problems.append("the sampler accepted a spec it should refuse")
    except RandomizationError as exc:
        if unmapped:
            if exc.constraint != "randomization.vocabulary":
                problems.append(f"refused {exc.constraint}, expected vocabulary")
            if not all(f'"{s}"' in exc.message for s in unmapped):
                problems.append(f"the sentence is not quoted: {exc.message}")
        elif "refused" in expected:
            if exc.constraint != expected["refused"]:
                problems.append(f"refused {exc.constraint}, expected {expected['refused']}")
        else:
            problems.append(f"sampler refused {exc.constraint}: {exc.message[:80]}")
    return problems


def _family_leaves(leaf):
    """Every documented distribution some family writes for ``leaf``."""
    return [family[leaf] for family in RANDOMIZATION_FAMILIES.values()
            if leaf in family]


def test_the_randomization_corpus_scores_100_percent():
    misses = {}
    for prompt, expected in CORPUS:
        problems = _score(prompt, expected)
        if problems:
            misses[prompt] = problems
    rate = 1.0 - len(misses) / len(CORPUS)
    print(f"randomization corpus: {len(CORPUS) - len(misses)}/{len(CORPUS)} "
          f"({100 * rate:.0f}%)")
    assert not misses, misses


def test_a_location_phrase_is_a_choice_of_that_range_only():
    spec = compile_prompt("fly the cessna over the alps")
    assert spec.randomization_policy.value["location"] == {"choice": ["alps"]}
    rockies = compile_prompt("fly the cessna across the rocky mountains")
    assert rockies.randomization_policy.value["location"] == {"choice": ["rockies"]}
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(rockies)
    assert caught.value.constraint == "randomization.location"
    assert "rockies" in caught.value.message


def test_an_unmapped_variation_refuses_by_name_on_every_sampling_surface():
    """The compiled spec carries the sentence; the page's verdict, /run,
    the capture command and a batch all go through the sampler."""
    from webapp.runs import sample_randomization_or_refuse

    spec = compile_prompt("fly the 747 and vary the moon phase")
    refusal = sample_randomization_or_refuse(spec)
    assert refusal["constraint"] == "randomization.vocabulary"
    assert '"fly the 747 and vary the moon phase"' in refusal["message"]
    from fastapi.testclient import TestClient

    from webapp.server import app

    verdict = TestClient(app).post("/compile", json={
        "prompt": "fly the 747 and vary the moon phase",
        "compiler": "regex"}).json()["validation"]
    assert verdict["ok"] is False
    assert any(v["constraint"] == "randomization.vocabulary"
               for v in verdict["violations"])


def test_no_variation_language_leaves_the_spec_byte_identical():
    for prompt in ("fly the 747 at 10000 ft and 280 kt for 60 seconds, chase view",
                   "chase view of the 747 at 3000 m and 250 kt",
                   "epic cinematic flyby of the 747 over mountains"):
        spec = compile_prompt(prompt)
        assert spec.randomization_policy is None
        assert "randomization" not in spec.to_dict()
        assert not any("randomization" in n for n in spec.notes)


def test_the_intent_words_are_the_documented_ones():
    import re

    for word in ("vary", "varied", "varying", "variety", "random", "randomly",
                 "randomise", "randomized", "assorted", "various"):
        assert re.search(VARIATION_INTENT, word), word
    for word in ("different", "mixed", "randomization"):
        assert not re.search(VARIATION_INTENT, word), word


def test_a_viewpoint_policy_gets_one_default_camera_that_the_sampler_varies():
    spec = compile_prompt("random viewpoints of the 747 at 3000 m for 20 seconds")
    camera, = spec.cameras
    assert camera.preset.source is Source.DEFAULT
    assert str(camera.trigger.value) == "continuous"
    sample_randomization(spec)
    camera, = spec.cameras           # the committed draw is a fresh object
    assert camera.preset.source is Source.SAMPLED
    assert str(camera.preset.value) in ("chase", "tower", "wingman", "ground")
    assert 24.0 <= float(camera.focal_length_mm.value) <= 400.0
