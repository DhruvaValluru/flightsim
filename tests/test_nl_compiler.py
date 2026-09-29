"""The compiler emits a spec and never runs anything (§2.6).

It is rule-based and therefore deterministic: the same sentence always produces
the same spec. That guarantee is what the reproducibility claim rests on.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.scenario.fields import Source


def test_same_prompt_always_produces_the_same_spec():
    prompt = "fly the 747 at 10000 ft and 280 kt into a strong crosswind"
    digests = {compile_prompt(prompt).digest() for _ in range(5)}
    assert len(digests) == 1


def test_explicit_numbers_are_attributed_to_the_user():
    s = compile_prompt("fly the 737 at 6000 m and 250 kt")
    assert s.altitude.value == 6000.0 and s.altitude.source is Source.USER
    assert s.airspeed.value == 250.0 and s.airspeed.source is Source.USER


def test_vague_phrases_are_marked_inferred_not_user():
    """The distinction a reviewer needs: stated versus guessed."""
    s = compile_prompt("fly the 747 into a strong crosswind")
    assert s.wind_speed.source is Source.INFERRED
    assert s.wind_speed.value == 25.0


def test_unmentioned_values_are_marked_default():
    s = compile_prompt("fly the 747")
    assert s.turbulence.source is Source.DEFAULT
    assert s.latitude.source is Source.DEFAULT


def test_turbulence_words_carry_a_citation_not_a_magic_number():
    """§2.5: a plugin must answer 'what does moderate mean' with a standard."""
    s = compile_prompt("fly the 747 in moderate turbulence")
    assert s.turbulence.value == "moderate"
    assert "MIL-F-8785C" in s.turbulence.std
    assert s.turbulence.detail["W20_kt"] == 30.0


def test_terrain_number_is_not_read_as_the_altitude():
    """Both are '<number> m' and the terrain figure usually comes second.

    Before the fix this fell back to the default altitude of 3000 m, which
    happened to equal the terrain height in the §5 example and so produced the
    right rejection for entirely the wrong reason.
    """
    s = compile_prompt("land the 747 at 400 kt at 300 m altitude over 3000 m terrain")
    assert s.altitude.value == 300.0
    assert s.terrain_elevation.value == 3000.0


def test_terrain_stated_before_the_altitude_is_still_not_read_as_altitude():
    """The ordering that actually requires the terrain clause to be removed.

    When terrain comes first it is the leftmost '<number> m' in the sentence, so
    a plain left-to-right search returns it. The case above happens to pass
    either way, which is why it is not sufficient on its own.
    """
    s = compile_prompt("over 3000 m terrain, fly the 747 at 4500 m and 280 kt")
    assert s.terrain_elevation.value == 3000.0
    assert s.altitude.value == 4500.0


@pytest.mark.parametrize(
    "prompt,expected_m",
    [
        ("cruise at FL350", 10668.0),
        ("fly at 10000 ft", 3048.0),
        ("fly at 6000 m", 6000.0),
    ],
)
def test_altitude_units(prompt, expected_m):
    assert compile_prompt(prompt).altitude.value == pytest.approx(expected_m, abs=0.5)


def test_relative_wind_direction_is_resolved_against_heading():
    s = compile_prompt("fly heading 090 into a 20 kt crosswind")
    assert s.heading.value == 90.0
    # Meteorological: a crosswind for an easterly heading blows from the south.
    assert s.wind_direction.value == pytest.approx(180.0)
    assert s.wind_direction.detail["rel_to"] == "aircraft heading"


def test_cinematic_terms_are_reported_as_ignored_not_silently_dropped():
    """§8: the vocabulary is conditions-first, and says so when asked for a shot."""
    s = compile_prompt("epic cinematic flyby of the 747 over mountains")
    assert any("cinematic" in n for n in s.notes)
    # and nothing in the spec was set from them
    assert s.airspeed.source is Source.DEFAULT


# -- cameras (Camera Phase 1) --------------------------------------------

def test_camera_view_words_map_to_presets():
    s = compile_prompt("cockpit view of the 747 at 3000 m and 250 kt")
    assert len(s.cameras) == 1
    camera = s.cameras[0]
    assert str(camera.preset.value) == "cockpit"
    assert camera.preset.source is Source.INFERRED
    assert camera.preset.frm == "cockpit"


def test_image_counts_are_attributed_to_the_user():
    s = compile_prompt("50 images of the 747 from the tower")
    camera = s.cameras[0]
    assert str(camera.preset.value) == "tower"
    assert camera.capture_count.value == 50
    assert camera.capture_count.source is Source.USER
    assert "50 images" in camera.capture_count.frm


def test_lens_words_carry_the_documented_mapping():
    s = compile_prompt("wide angle chase view of the 747")
    camera = s.cameras[0]
    assert str(camera.preset.value) == "chase"
    assert camera.focal_length_mm.value == 24.0
    assert camera.focal_length_mm.source is Source.INFERRED
    assert "documented mapping" in camera.focal_length_mm.frm

    stated = compile_prompt("film the 747 with a 85 mm lens")
    assert stated.cameras[0].focal_length_mm.value == 85.0
    assert stated.cameras[0].focal_length_mm.source is Source.USER


def test_no_camera_language_means_no_cameras():
    """The empty list IS the documented default (byte-identical render
    behaviour, pinned in test_camera_spec)."""
    assert compile_prompt("fly the 747 at 3000 m").cameras == []


def test_mapped_camera_words_are_no_longer_reported_ignored():
    s = compile_prompt("chase view of the 747")
    assert s.cameras
    assert not any("chase" in n for n in s.notes)
    # Genuinely unexpressible shot language still goes to notes.
    t = compile_prompt("epic cinematic flyby of the 747")
    assert any("cinematic" in n for n in t.notes)


def test_camera_defaults_follow_the_airframe():
    s = compile_prompt("chase view of the cessna")
    from core.scenario.camera import CHASE_OFFSETS

    assert float(s.cameras[0].offset_forward_m.value) == \
        CHASE_OFFSETS["c172p"][0]


# -- randomisation phrases (spec 8, package F) ----------------------------

def test_variation_phrases_write_an_attributed_inferred_policy():
    s = compile_prompt("fly the 747 at 3000 m in varied weather")
    policy = s.randomization_policy
    assert policy.source is Source.INFERRED
    assert policy.frm == "varied weather"
    assert set(policy.value) == {"cloud_cover", "visibility_km", "precipitation"}
    assert policy.detail["attribution"] == {"cloud_cover": "varied weather",
                                            "visibility_km": "varied weather",
                                            "precipitation": "varied weather"}
    assert s.randomization.enabled.value is True
    assert s.randomization.enabled.source is Source.INFERRED
    assert "varied weather" in s.randomization.enabled.frm
    # The prompt's other words compile exactly as before.
    assert s.altitude.value == 3000.0 and s.altitude.source is Source.USER


def test_an_unmapped_variation_is_recorded_for_the_by_name_refusal_not_a_note():
    from core.scenario.randomization import RandomizationError, sample_randomization

    s = compile_prompt("fly the 747 at 3000 m. vary the moon phase")
    assert s.randomization_policy.detail["unmapped"] == ["vary the moon phase"]
    assert not s.randomization.is_enabled()
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(s)
    assert caught.value.constraint == "randomization.vocabulary"
    assert '"vary the moon phase"' in caught.value.message
    assert not any("moon" in n for n in s.notes)


# -- the second aircraft (spec 8, contracts §2.2) -------------------------

def test_a_traffic_clause_fills_the_traffic_block_with_provenance():
    """Before this, 'with an A320 crossing' compiled to traffic [] and
    notes []: the second aircraft was neither planned nor reported."""
    s = compile_prompt("chase the 747 at 10000 ft for 30 seconds with an A320 crossing")
    assert str(s.aircraft.value) == "B747" and s.aircraft.source is Source.USER
    assert len(s.traffic) == 1
    t = s.traffic[0]
    assert str(t.aircraft.value) == "A320" and t.aircraft.source is Source.USER
    assert t.aircraft.frm == "with an a320 crossing"
    assert str(t.track.value) == "crossing" and t.track.source is Source.USER
    assert t.range_m.source is Source.DEFAULT and float(t.range_m.value) == 400.0
    assert s.notes == []
    assert s.to_dict()["traffic"][0]["aircraft"]["value"] == "A320"


def test_a_traffic_range_is_the_traffic_s_and_never_the_altitude():
    s = compile_prompt("a B747 with an A320 crossing 400 m ahead")
    assert float(s.traffic[0].range_m.value) == 400.0
    assert s.traffic[0].range_m.source is Source.USER
    assert s.altitude.source is Source.DEFAULT       # 400 m is not an altitude
    km = compile_prompt("chase the 747 at 3000 m with a 737 in formation "
                        "and a cessna overtaking 1 km behind")
    assert [str(t.aircraft.value) for t in km.traffic] == ["737", "c172p"]
    assert [str(t.track.value) for t in km.traffic] == ["formation", "overtaking"]
    assert float(km.traffic[1].range_m.value) == 1000.0
    assert km.altitude.value == 3000.0 and km.altitude.source is Source.USER


def test_the_primary_s_own_crossing_is_not_traffic():
    s = compile_prompt("chase the 747 crossing the alps at 3000 m")
    assert s.traffic == [] and str(s.aircraft.value) == "B747"


def test_a_second_airframe_the_compiler_cannot_place_is_reported_not_dropped():
    s = compile_prompt("chase the 747 at 3000 m, the a320 is nearby")
    assert s.traffic == []
    assert any("second aircraft 'a320'" in n and "crossing" in n for n in s.notes)
    # The same model named twice is one aircraft, not a second.
    assert not any("second aircraft" in n
                   for n in compile_prompt("chase the 747, the jumbo").notes)


def test_a_third_traffic_aircraft_is_recorded_and_refused_by_name():
    from core.scenario.validate import validate

    s = compile_prompt("chase the 747 with an a320 crossing and a cessna "
                       "overtaking and a 737 in formation")
    assert len(s.traffic) == 3
    names = [v.constraint for v in validate(s, check_feasibility=False).violations]
    assert "traffic.count" in names


# -- duration: a bare 'm' is metres --------------------------------------

def test_over_n_m_terrain_is_terrain_not_a_flight_of_n_minutes():
    """The report's own page demo, 'over 2000 m terrain', compiled to
    a 120000 s flight (source user) and a 1,200,001-frame case."""
    s = compile_prompt("fly the 747 at 500 m over 2000 m terrain, chase view")
    assert s.duration.source is Source.DEFAULT and s.duration.value == 120.0
    assert s.terrain_elevation.value == 2000.0 and s.altitude.value == 500.0
    assert compile_prompt("fly the 747 for 5 minutes").duration.value == 300.0
    assert compile_prompt("fly the 747 for 2 min").duration.value == 120.0
    assert compile_prompt("fly the 747 for 45 seconds").duration.value == 45.0


# -- randomisation conjunctions -------------------------------------------

def test_varied_weather_and_lighting_varies_both():
    """'in varied weather and lighting' wrote the weather leaves only:
    every campaign case shared one day, hour and sun (measured)."""
    s = compile_prompt("500 images of airliners in varied weather and lighting, chase view")
    policy = s.randomization_policy.value
    assert set(policy) == {"cloud_cover", "visibility_km", "precipitation",
                           "hour_local", "weather_date"}
    attribution = s.randomization_policy.detail["attribution"]
    assert attribution["hour_local"] == "varied lighting"
    assert attribution["cloud_cover"] == "varied weather"
    lst = compile_prompt("fly the 747 in varied weather, lighting and times of day")
    assert set(lst.randomization_policy.value) == set(policy)
    assert "unmapped" not in lst.randomization_policy.detail


def test_varied_lighting_makes_the_cases_differ():
    from core.scenario.randomization import sample_randomization

    hours = set()
    for index in range(3):
        s = compile_prompt("500 images of the 747 in varied weather and lighting, chase view")
        sample_randomization(s, draw_index=index)
        hours.add(round(float(s.randomization.hour_utc.value), 4))
    assert len(hours) == 3


def test_an_item_the_vocabulary_cannot_vary_is_reported_not_dropped():
    s = compile_prompt("fly the 747 in varied weather and altitude, chase view")
    assert set(s.randomization_policy.value) == {"cloud_cover", "visibility_km",
                                                 "precipitation"}
    assert any("cannot vary 'altitude'" in n for n in s.notes)
    # A view after the conjunction is the sentence moving on, not an item.
    assert compile_prompt("fly the 747 in varied weather and chase views").notes == []


# -- the aircraft the person named ------------------------------------------

def test_an_unrecognised_aircraft_is_never_replaced_by_the_default():
    """'photos of a dragon' compiled, validated and planned as the B747
    with ok: true. The name the person used is carried as stated and
    refused by name; the page asks which aircraft first."""
    from core.nl.compiler import (AIRCRAFT_OPTIONS, AIRCRAFT_QUESTION_ID,
                                  camera_questions)
    from core.scenario.validate import validate

    for prompt in ("photos of a dragon for 2 seconds, chase view",
                   "fly the dragon at 3000 m for 2 seconds, chase view",
                   "photos of a pilatus pc-12 over yosemite"):
        s = compile_prompt(prompt)
        assert s.aircraft.source is Source.USER, prompt
        assert str(s.aircraft.value) in ("dragon", "pilatus pc-12")
        names = [v.constraint for v in validate(s).violations]
        assert names == ["aircraft.exists"], prompt
        questions = camera_questions(prompt)
        assert questions[0]["id"] == AIRCRAFT_QUESTION_ID
        assert questions[0]["options"] == list(AIRCRAFT_OPTIONS)


def test_the_aircraft_answer_compiles_and_an_unknown_answer_is_refused_by_name():
    from core.nl.compiler import AIRCRAFT_QUESTION_ID
    from core.scenario.validate import validate

    prompt = "fly the dragon at 3000 m for 2 seconds, chase view"
    answered = compile_prompt(prompt, answers=[{"id": AIRCRAFT_QUESTION_ID,
                                                "answer": "Airbus A320"}])
    assert str(answered.aircraft.value) == "A320"
    assert answered.aircraft.source is Source.USER
    assert 'answer to "Which aircraft should fly?": "Airbus A320"' == answered.aircraft.frm
    assert validate(answered, check_feasibility=False).ok
    unknown = compile_prompt(prompt, answers=[{"id": AIRCRAFT_QUESTION_ID,
                                               "answer": "unicorn"}])
    assert str(unknown.aircraft.value) == "unicorn"
    assert [v.constraint for v in validate(unknown).violations] == ["aircraft.exists"]


def test_a_kind_of_aircraft_earns_the_question_and_keeps_the_documented_default():
    from core.nl.compiler import AIRCRAFT_QUESTION_ID, camera_questions

    s = compile_prompt("500 images of airliners in varied weather, chase view")
    assert str(s.aircraft.value) == "B747" and s.aircraft.source is Source.DEFAULT
    assert [q["id"] for q in camera_questions(
        "500 images of airliners in varied weather, chase view")] == [AIRCRAFT_QUESTION_ID]
    # A known type or no subject at all: nothing to ask, as before.
    assert camera_questions("fly the 747 at 3000 m") == []
    assert camera_questions("fly at 6000 m") == []
    assert [q["id"] for q in camera_questions("film the sunrise over the alps")] == ["camera_view"]
    assert str(compile_prompt("fly at 6000 m").aircraft.source) == "default"
