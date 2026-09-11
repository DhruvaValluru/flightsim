"""Camera Phase 1, package F, closed: the regex camera vocabulary
measured on a corpus, not assumed.

Every view named in a sentence is a camera; counts and lenses apply to
each; simple move phrases become keyframes; a prompt that speaks of
imagery and names no view earns the one clarifying question, whose
answer compiles; the clip selector rescales prompt moves. The corpus
below is scored as a whole and the score must be 100%: a case that
stops matching is a vocabulary regression, named.
"""

import pytest

from core.nl.compiler import (
    CAMERA_QUESTION_ID, CAMERA_VIEW_OPTIONS, ORBIT_SEGMENTS, camera_questions,
    compile_prompt, move_keyframes, rescale_moves,
)

# (prompt, expected) -- expected keys: presets (ordered camera ids),
# count, focal_mm, moves (set of kinds on the first camera), question.
CORPUS = [
    ("fly the 747 at 3000 m and 250 kt",
     {"presets": [], "question": False}),
    ("chase view of the 747 at 3000 m and 250 kt",
     {"presets": ["chase"], "count": 0, "question": False}),
    ("fly the 747 at 3000 m and 250 kt, 40 images from the tower",
     {"presets": ["tower"], "count": 40, "question": False}),
    ("cockpit view of the a320 at 5000 m and 250 kt",
     {"presets": ["cockpit"], "question": False}),
    ("capture 25 stills of a cessna from the control tower",
     {"presets": ["tower"], "count": 25, "question": False}),
    ("a wide angle chase of the jumbo jet in moderate turbulence",
     {"presets": ["chase"], "focal_mm": 24.0, "question": False}),
    ("telephoto wingman shot of the f16 at 8000 ft",
     {"presets": ["wingman"], "focal_mm": 85.0, "question": False}),
    ("a 50 mm lens on the ground observer, 12 photos of the cessna",
     {"presets": ["ground"], "focal_mm": 50.0, "count": 12, "question": False}),
    ("chase and wingman views of the 747 at 3000 m for 20 seconds",
     {"presets": ["chase", "wingman"], "question": False}),
    ("from the tower and from the ground, 30 frames of the a320",
     {"presets": ["tower", "ground"], "count": 30, "question": False}),
    ("cockpit, chase and tower views of the cessna at 2000 ft",
     {"presets": ["cockpit", "chase", "tower"], "question": False}),
    ("chase the 747, chase it closely",
     {"presets": ["chase"], "question": False}),          # one camera per preset
    ("photograph a 747 in flight",
     {"presets": ["chase"], "question": True}),           # default view + question
    ("50 images of the jumbo at 10000 ft",
     {"presets": ["chase"], "count": 50, "question": True}),
    ("film the f16 at 500 kt",
     {"presets": ["chase"], "question": True}),
    ("render the cessna over yosemite",
     {"presets": ["chase"], "question": True}),
    ("chase view of the 747 for 30 seconds, zoom in",
     {"presets": ["chase"], "moves": {"zoom_in"}, "question": False}),
    ("wingman view of the a320 for 20 seconds, zoom out slowly",
     {"presets": ["wingman"], "moves": {"zoom_out"}, "question": False}),
    ("chase the 747 for 40 seconds and pull back",
     {"presets": ["chase"], "moves": {"pull_back"}, "question": False}),
    ("chase view, push in on the cessna over 15 seconds",
     {"presets": ["chase"], "moves": {"push_in"}, "question": False}),
    ("orbit the 747 from the chase camera for 60 seconds",
     {"presets": ["chase"], "moves": {"orbit"}, "question": False}),
    ("wingman view of the f15, circle around it and zoom in",
     {"presets": ["wingman"], "moves": {"orbit", "zoom_in"}, "question": False}),
    ("from the tower, zoom in on the 747 for 30 seconds",
     {"presets": ["tower"], "moves": {"zoom_in"}, "question": False}),
    ("from the tower, pull back from the 747",
     {"presets": ["tower"], "moves": set(), "ignored": True, "question": False}),
    ("cockpit view, orbit the a320",
     {"presets": ["cockpit"], "moves": set(), "ignored": True, "question": False}),
    ("chase view of the 747, pan left across the ridge",
     {"presets": ["chase"], "moves": set(), "question": False}),
]


def _score(prompt, expected):
    spec = compile_prompt(prompt)
    problems = []
    presets = [str(c.camera_id.value) for c in spec.cameras]
    if presets != expected["presets"]:
        problems.append(f"cameras {presets} != {expected['presets']}")
    if presets and [str(c.preset.value) for c in spec.cameras] != presets:
        problems.append("camera ids are not the preset names")
    asked = bool(camera_questions(prompt))
    if asked != expected["question"]:
        problems.append(f"question asked={asked}, expected {expected['question']}")
    if spec.cameras:
        first = spec.cameras[0]
        if "count" in expected and int(first.capture_count.value) != expected["count"]:
            problems.append(f"count {first.capture_count.value} != {expected['count']}")
        if "focal_mm" in expected and float(first.focal_length_mm.value) != expected["focal_mm"]:
            problems.append(f"focal {first.focal_length_mm.value} != {expected['focal_mm']}")
        if "moves" in expected:
            kinds = set()
            for note in spec.notes:
                if note.startswith("move '") and f"on the {presets[0]} view" in note:
                    kinds.add(note.split(" -> ")[1].split(" ")[0])
            if kinds != expected["moves"]:
                problems.append(f"moves {kinds} != {expected['moves']}")
            if expected["moves"] and not first.moves:
                problems.append("expected keyframes, camera has none")
        if expected.get("ignored") and not any("ignored move" in n for n in spec.notes):
            problems.append("an inexpressible move was not reported as ignored")
        # Every camera named gets the same count and lens.
        for camera in spec.cameras[1:]:
            if int(camera.capture_count.value) != int(first.capture_count.value):
                problems.append("count differs between the named cameras")
            if float(camera.focal_length_mm.value) != float(first.focal_length_mm.value):
                problems.append("lens differs between the named cameras")
    return problems


def test_the_camera_corpus_scores_100_percent():
    """The measurement: every case, scored, reported as a rate. A miss
    is named with its prompt."""
    misses = {}
    for prompt, expected in CORPUS:
        problems = _score(prompt, expected)
        if problems:
            misses[prompt] = problems
    rate = 1.0 - len(misses) / len(CORPUS)
    print(f"camera corpus: {len(CORPUS) - len(misses)}/{len(CORPUS)} "
          f"({100 * rate:.0f}%)")
    assert not misses, misses


def test_every_named_view_is_its_own_camera_with_shared_count_and_lens():
    spec = compile_prompt("chase and wingman views of the 747 at 3000 m, "
                          "30 images, telephoto")
    assert [str(c.camera_id.value) for c in spec.cameras] == ["chase", "wingman"]
    for camera in spec.cameras:
        assert int(camera.capture_count.value) == 30
        assert float(camera.focal_length_mm.value) == 85.0
        assert str(camera.preset.source) == "inferred"
    assert spec.digest() != compile_prompt(
        "chase view of the 747 at 3000 m, 30 images, telephoto").digest()


def test_move_phrases_become_the_documented_keyframes():
    spec = compile_prompt("chase view of the 747 for 20 seconds, zoom in and orbit")
    camera = spec.cameras[0]
    times = sorted({m["t_s"] for m in camera.moves})
    assert times[0] == 0.0 and times[-1] == 20.0
    assert len(times) == ORBIT_SEGMENTS + 1
    first, last = camera.moves[0], camera.moves[-1]
    assert first["focal_length_mm"] == 35.0 and last["focal_length_mm"] == 70.0
    # The orbit closes: the last keyframe's offset is the first's.
    assert last["offset_forward_m"] == pytest.approx(first["offset_forward_m"], abs=1e-6)
    assert last["offset_right_m"] == pytest.approx(first["offset_right_m"], abs=1e-6)
    # A quarter of the way round, forward has become right.
    quarter = camera.moves[ORBIT_SEGMENTS // 4]
    assert quarter["offset_right_m"] == pytest.approx(first["offset_forward_m"], abs=1e-6)
    pull = compile_prompt("wingman view of the a320 for 10 seconds, pull back").cameras[0]
    assert pull.moves[-1]["offset_forward_m"] == pytest.approx(
        2.0 * pull.moves[0]["offset_forward_m"])
    push = compile_prompt("wingman view of the a320 for 10 seconds, push in").cameras[0]
    assert push.moves[-1]["offset_forward_m"] == pytest.approx(
        0.5 * push.moves[0]["offset_forward_m"])
    with pytest.raises(ValueError):
        move_keyframes("barrel_roll", camera, 10.0)


def test_the_moves_solve_and_validate_end_to_end():
    """The keyframes the vocabulary writes are the keyframes the solver
    reads: an orbit puts the chase camera on the far side of the
    aircraft halfway through, and the validator accepts them."""
    from core.capture.poses import SceneFrame, solve_pose_track
    from core.scenario.validate import validate
    from tests.test_camera_poses import make_columns

    spec = compile_prompt("orbit the 747 from the chase camera for 20 seconds")
    assert validate(spec, check_feasibility=False).ok
    camera = spec.cameras[0]
    columns = make_columns(duration_s=20.0, dt=0.1)
    frame = SceneFrame.for_spec(spec, None)
    track = solve_pose_track(columns, camera, frame)
    start = columns["t"].index(0.0)
    half = columns["t"].index(10.0)
    # Behind at the start (offset forward is negative), ahead at half.
    assert track.north_m[start] < float(columns["lat_deg"][start]) * 0 + 1e9
    behind = track.north_m[start] - frame.to_local(
        float(columns["lat_deg"][start]), float(columns["lon_deg"][start]))[0]
    ahead = track.north_m[half] - frame.to_local(
        float(columns["lat_deg"][half]), float(columns["lon_deg"][half]))[0]
    assert behind < 0 < ahead


def test_a_keyframe_with_an_unknown_key_refuses_by_name():
    from core.scenario.validate import validate

    spec = compile_prompt("chase view of the 747")
    spec.cameras[0].moves = [{"t_s": 0.0, "focal_length_mm": 35.0},
                             {"t_s": 5.0, "roll_deg": 30.0}]
    names = [v.constraint for v in validate(spec, check_feasibility=False).violations]
    assert "camera.moves" in names
    spec.cameras[0].moves = [{"t_s": -1.0, "focal_length_mm": 35.0}, {"t_s": 2.0}]
    report = validate(spec, check_feasibility=False)
    assert sum(v.constraint == "camera.moves" for v in report.violations) == 2
    spec.cameras[0].moves = [{"t_s": 0.0, "focal_length_mm": "wide"}]
    assert any(v.constraint == "camera.moves" for v in
               validate(spec, check_feasibility=False).violations)


def test_the_regex_question_is_asked_once_and_its_answer_compiles():
    questions = camera_questions("photograph a 747 in flight")
    assert questions[0]["id"] == CAMERA_QUESTION_ID
    assert questions[0]["options"] == list(CAMERA_VIEW_OPTIONS)
    assert camera_questions("chase view of the 747") == []
    assert camera_questions("fly the 747 at 3000 m") == []
    answered = compile_prompt("photograph a 747 in flight",
                              answers=[{"id": CAMERA_QUESTION_ID, "answer": "from the tower"}])
    assert [str(c.camera_id.value) for c in answered.cameras] == ["tower"]
    assert str(answered.cameras[0].preset.source) == "inferred"
    plain = compile_prompt("photograph a 747 in flight",
                           answers=[{"id": CAMERA_QUESTION_ID, "answer": "dunno"}])
    assert [str(c.camera_id.value) for c in plain.cameras] == ["chase"]
    assert str(plain.cameras[0].preset.source) == "default"


def test_the_compile_endpoint_asks_and_the_answer_round_does_not():
    from fastapi.testclient import TestClient

    from webapp.server import app

    client = TestClient(app)
    first = client.post("/compile", json={"prompt": "photograph a 747 in flight",
                                          "compiler": "regex"}).json()
    assert first["needs_clarification"] is True
    assert first["questions"][0]["id"] == CAMERA_QUESTION_ID
    assert first["spec"]["cameras"][0]["camera_id"] == "chase"
    second = client.post("/compile", json={
        "prompt": "photograph a 747 in flight", "compiler": "regex",
        "questions": first["questions"],
        "answers": [{"id": CAMERA_QUESTION_ID, "answer": "wingman"}],
        "prior_spec": first["spec"]["dict"]}).json()
    assert second["needs_clarification"] is False
    assert second["spec"]["cameras"][0]["camera_id"] == "wingman"
    named = client.post("/compile", json={"prompt": "chase view of the 747",
                                          "compiler": "regex"}).json()
    assert named["needs_clarification"] is False


def test_the_clip_selector_rescales_prompt_moves():
    spec = compile_prompt("chase view of the 747 for 60 seconds, zoom in")
    assert spec.cameras[0].moves[-1]["t_s"] == 60.0
    assert rescale_moves(spec, 60.0, 15.0) == 1
    assert spec.cameras[0].moves[-1]["t_s"] == 15.0
    assert spec.cameras[0].moves[-1]["focal_length_mm"] == 70.0
    # Stated keyframes that do not end at the old duration are left alone.
    spec.cameras[0].moves = [{"t_s": 0.0, "focal_length_mm": 35.0},
                             {"t_s": 7.0, "focal_length_mm": 50.0}]
    assert rescale_moves(spec, 15.0, 5.0) == 0
    from fastapi.testclient import TestClient

    from webapp.server import app

    payload = TestClient(app).post("/compile", json={
        "prompt": "chase view of the 747 for 60 seconds, zoom in",
        "compiler": "regex", "clip_seconds": 6}).json()
    moves = payload["spec"]["cameras"][0]["moves"]
    assert moves[-1]["t_s"] == 6.0
