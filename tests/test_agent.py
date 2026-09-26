"""Phase 2, package H: the agentic controller with stated authority
(contracts §7; brainstorm §7).

The tool layer is ten typed functions over the library that exists;
the policy denies BY NAME (``authority.stated_field``,
``authority.validation_token``, ``authority.refusal_is_not_a_run``,
``authority.budget``) and every call is a line of ``trace.jsonl``. A
scripted rogue agent tries each violation here and is denied; a
cooperative scripted agent completes a tiny headless campaign end to
end (two cases, no engine) with the trace explaining each decision in
one sentence. No model is used anywhere in this file.

The checks re-implement what they verify: the token is recomputed
from the digest here, the provenance comparison walks the spec dict
here, the trace is read as JSON lines here -- never through the
functions that produced them.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.agent import Budget, Controller, Policy, Request, Tools, mint_token
from core.agent.policy import Denial, expected_token, flatten, stated_moves
from core.agent.tools import EQUIVALENTS, TOOL_NAMES, schemas, tool_schema
from core.messages import render

REPO = Path(__file__).resolve().parents[1]

#: One continuous chase camera over 5 s at the recorder's 0.1 s cadence
#: is ~48 measured frames per case (51 estimated); 90 images is two cases.
PROMPT = ("fly the a320 at 3000 m for 5 seconds in varied weather at "
          "different times of day, chase view")
IMAGES = 90
#: Refused by the validator: 40 kt is below the 747's stall margin.
UNFLYABLE = "fly the 747 at 10000 ft and 40 kt for 5 seconds, chase view"
#: A c172p cannot trim at 280 kt: a policy that only draws it exhausts
#: every slot (``randomization.infeasible``); the stated fields stay.
FAST = "fly at 10000 ft and 280 kt for 5 seconds, chase view"
INFEASIBLE_POLICY = {"aircraft": {"choice": ["c172p"]}}


def _tools(path, **kw) -> Tools:
    kw.setdefault("stall_seconds", 120)
    return Tools(path, **kw)


def _stated(flat):
    return {p: q for p, q in flat.items() if q["source"] in ("user", "inferred", "sampled")}


def _trace(path):
    """The trace read as JSON lines, here, not through Trace."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


# -- the tool layer: schemas, the doc, the equivalents -------------------------------

def test_the_ten_tool_schemas_are_drawn_from_the_signatures_and_the_doc_is_current():
    listed = schemas()
    assert [s["name"] for s in listed] == list(TOOL_NAMES)
    assert len(listed) == 10 and set(EQUIVALENTS) == set(TOOL_NAMES)
    by_name = {s["name"]: s for s in listed}
    assert by_name["compile"]["parameters"]["required"] == ["prompt"]
    assert by_name["run"]["parameters"]["required"] == ["case_id", "validation_token"]
    assert by_name["render"]["parameters"]["required"] == ["run_id", "validation_token"]
    assert by_name["export"]["parameters"]["required"] == ["campaign_id", "format", "validation_token"]
    assert by_name["verify"]["parameters"]["required"] == ["run_id"]
    assert by_name["plan_campaign"]["parameters"]["properties"]["images"] == {
        "type": "integer", "default": 100}
    assert by_name["sample"]["parameters"]["properties"]["start"]["type"] == ["integer", "null"]
    for schema in listed:
        assert schema["description"].endswith(".") and schema["parameters"]["type"] == "object"
        assert schema["parameters"]["additionalProperties"] is False

    def f(a: str, b: int = 2, c: bool = False) -> dict:
        """First paragraph, one sentence.

        Second paragraph is not the description."""
        return {}

    assert tool_schema(f) == {
        "name": "f", "description": "First paragraph, one sentence.",
        "parameters": {"type": "object", "properties": {
            "a": {"type": "string"}, "b": {"type": "integer", "default": 2},
            "c": {"type": "boolean", "default": False}},
            "required": ["a"], "additionalProperties": False}}
    # docs/COMMANDS.md is what the generator writes, byte for byte, and
    # names every tool with a CLI and a UI equivalent.
    generated = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "agent_commands.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    assert generated.returncode == 0, generated.stdout + generated.stderr
    doc = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    for name in TOOL_NAMES:
        assert f"## `{name}`" in doc and EQUIVALENTS[name]["cli"] in doc
    # The MCP tool list is the same schema; the server is optional and
    # says so by name without the package.
    from core.agent.mcp_server import MCP_MISSING, mcp_tools, serve

    assert [t["name"] for t in mcp_tools()] == list(TOOL_NAMES)
    assert all("inputSchema" in t for t in mcp_tools())
    try:
        import mcp  # noqa: F401
    except ImportError:
        assert serve("/nonexistent") == 2 and "pip install mcp" in MCP_MISSING


def test_an_unknown_tool_is_a_programming_error_not_a_refusal(tmp_path):
    with pytest.raises(ValueError):
        _tools(tmp_path / "t").call("launch", reason="no such tool")


# -- the token --------------------------------------------------------------------------

def test_a_token_is_minted_only_by_validate_and_bound_to_the_digest(tmp_path):
    tools = _tools(tmp_path / "t")
    compiled = tools.call("compile", prompt=PROMPT, reason="interpret")
    assert compiled["refusals"] == [] and compiled["questions"] == []
    validated = tools.call("validate", spec=compiled["spec"], reason="validate")
    digest = validated["spec_digest"]
    assert validated["ok"] and digest == compiled["spec_digest"]
    # The token, recomputed here: sha256 of the digest and the word.
    assert validated["validation_token"] == hashlib.sha256(
        (digest + "validated").encode()).hexdigest()
    assert mint_token(digest) == expected_token(digest) == validated["validation_token"]
    # A refused spec gets none, and the refusal is by name with a sentence.
    refused = tools.call("compile", prompt=UNFLYABLE, reason="interpret")
    assert [r["constraint"] for r in refused["refusals"]] == ["airspeed.stall_margin"]
    assert refused["refusals"][0]["sentence"].startswith("A speed of 40 knots is too slow")
    denied = tools.call("validate", spec=refused["spec"], reason="validate anyway")
    assert denied["ok"] is False and denied["validation_token"] is None
    assert denied["violations"][0]["constraint"] == "airspeed.stall_margin"
    # Nothing here is a policy denial: the tools ran and said no by name.
    assert all(r["policy"] == {"ok": True} for r in _trace(tools.trace.path))


# -- the rogue agent ------------------------------------------------------------------------

def test_rogue_agent_cannot_overwrite_a_user_field(tmp_path):
    tools = _tools(tmp_path / "t")
    compiled = tools.call("compile", prompt=PROMPT, reason="interpret")
    spec = compiled["spec"]
    flat = flatten(spec)
    assert flat["initial.altitude"] == {"value": 3000.0, "source": "user", "from": "3000 m"}
    assert flat["randomization.policy"]["source"] == "inferred"
    # (a) move a user-stated value, keeping its provenance
    doctored = json.loads(json.dumps(spec))
    doctored["initial"]["altitude"]["value"] = 500.0
    denied = tools.call("validate", spec=doctored, reason="lower it quietly")
    assert denied["refused"] == "authority.stated_field"
    assert denied["sentence"] == render("authority.stated_field")
    assert "initial.altitude moved" in denied["message"]
    denied = tools.call("plan_campaign", spec=doctored, images=10, out=str(tmp_path / "t" / "c"),
                        reason="plan with the moved value")
    assert denied["refused"] == "authority.stated_field"
    assert not (tmp_path / "t" / "c").exists()               # nothing was created
    # (b) state a field on the person's behalf (a default promoted to user)
    promoted = json.loads(json.dumps(spec))
    promoted["environment"]["wind_speed"]["source"] = "user"
    promoted["environment"]["wind_speed"]["value"] = 30.0
    denied = tools.call("validate", spec=promoted, reason="claim the person said it")
    assert denied["refused"] == "authority.stated_field"
    assert "stated on the person's behalf" in denied["message"]
    # (c) move a system-chosen field without a recorded edit
    quiet = json.loads(json.dumps(spec))
    quiet["environment"]["wind_speed"]["value"] = 30.0     # still 'default', no edit recorded
    denied = tools.call("validate", spec=quiet, reason="nudge a default")
    assert denied["refused"] == "authority.stated_field"
    assert "without a recorded edit" in denied["message"]
    # (d) the policy words would move a stated policy
    denied = tools.call("plan_campaign", spec=spec, words="varied weather", images=10,
                        out=str(tmp_path / "t" / "w"), reason="add words over a stated policy")
    assert denied["refused"] == "authority.stated_field"
    # A recorded plan edit of a system-chosen field is allowed: derived, with a from.
    planned = json.loads(json.dumps(spec))
    planned["environment"]["wind_speed"].update(
        {"value": 30.0, "source": "derived", "from": "planned by the test"})
    allowed = tools.call("validate", spec=planned, reason="a recorded plan edit")
    assert allowed["ok"] and "refused" not in allowed
    # Every denial is in the trace, by rule name, with the caller's reason.
    denials = [r for r in _trace(tools.trace.path) if r["policy"].get("ok") is False]
    assert [d["policy"]["rule"] for d in denials] == ["authority.stated_field"] * 5
    assert [d["tool"] for d in denials] == ["validate", "plan_campaign", "validate",
                                            "validate", "plan_campaign"]
    assert denials[0]["reason"] == "lower it quietly"
    assert denials[0]["input"]["spec"] == {"spec_digest": denials[0]["input"]["spec"]["spec_digest"]}
    assert denials[0]["output"]["refused"] == "authority.stated_field"
    # The comparison itself, on flattened provenance.
    moves = stated_moves(flat, flatten(doctored))
    assert [(m["path"], m["kind"]) for m in moves] == [("initial.altitude", "moved")]
    assert stated_moves(flat, flatten(planned)) == []
    assert _stated(flat) == _stated(flatten(planned))


def test_rogue_agent_cannot_run_without_a_token(tmp_path):
    tools = _tools(tmp_path / "t")
    compiled = tools.call("compile", prompt=PROMPT, reason="interpret")
    planned = tools.call("plan_campaign", spec=compiled["spec"], images=IMAGES,
                         out=str(tmp_path / "t" / "c"), reason="plan")
    assert planned["refusals"] == [] and planned["campaign_id"] == "c"
    drawn = tools.call("sample", campaign_id="c", n=1, reason="preview")
    case_id = drawn["cases"][0]["case_id"]
    foreign = mint_token("0" * 64)                   # a token for some other digest
    for token in ("", None, "deadbeef", foreign):
        denied = tools.call("run", case_id=case_id, validation_token=token, reason="run anyway")
        assert denied["refused"] == "authority.validation_token", token
        assert denied["sentence"] == render("authority.validation_token")
    denied = tools.call("render", run_id=case_id, validation_token="", reason="render anyway")
    assert denied["refused"] == "authority.validation_token"
    denied = tools.call("export", campaign_id="c", format="coco", validation_token="x",
                        reason="export anyway")
    assert denied["refused"] == "authority.validation_token"
    # Nothing ran: the slot is still only sampled, no run directory exists.
    ledger = [json.loads(l) for l in (tmp_path / "t" / "c" / "ledger.jsonl")
              .read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in ledger] == ["sampled"]
    assert not (tmp_path / "t" / "c" / "runs" / case_id).exists()
    assert len([r for r in _trace(tools.trace.path)
                if r["policy"].get("rule") == "authority.validation_token"]) == 6
    # With the token validate() mints for THIS spec, the same call runs.
    token = tools.call("validate", spec=compiled["spec"], reason="validate")["validation_token"]
    ran = tools.call("run", case_id=case_id, validation_token=token, reason="run for real")
    assert ran["status"] == "verified" and ran["frames"] > 0 and ran["run_id"] == case_id
    assert (tmp_path / "t" / "c" / "runs" / case_id / "verification.json").is_file()
    # Idempotent on the case id: a second run of a verified case runs nothing.
    again = tools.call("run", case_id=case_id, validation_token=token, reason="again")
    assert again["status"] == "verified" and again["note"] == "already verified; not run again"


def test_rogue_agent_cannot_run_a_refused_spec(tmp_path):
    tools = _tools(tmp_path / "t")
    compiled = tools.call("compile", prompt=UNFLYABLE, reason="interpret")
    assert compiled["refusals"][0]["constraint"] == "airspeed.stall_margin"
    planned = tools.call("plan_campaign", spec=compiled["spec"], images=10,
                         out=str(tmp_path / "t" / "c"), reason="plan it anyway")
    assert planned["refusals"][0]["refused"] == "airspeed.stall_margin"
    assert planned["estimate"] is None and planned["campaign_id"] == "c"
    # The rogue forges the token (the digest is public; the token is HMAC-free).
    forged = mint_token(compiled["spec_digest"])
    denied = tools.call("run", case_id="c", validation_token=forged, reason="run it anyway")
    assert denied["refused"] == "authority.refusal_is_not_a_run"
    assert denied["sentence"] == render("authority.refusal_is_not_a_run")
    assert denied["message"].startswith("airspeed.stall_margin: A speed of 40 knots")
    assert denied["detail"]["refusals"] == ["airspeed.stall_margin"]
    assert not (tmp_path / "t" / "c" / "ledger.jsonl").exists()      # nothing ran
    assert json.loads((tmp_path / "t" / "c" / "campaign.json")
                      .read_text(encoding="utf-8"))["state"] == "planned"
    denials = [r for r in _trace(tools.trace.path) if r["policy"].get("ok") is False]
    assert [d["policy"]["rule"] for d in denials] == ["authority.refusal_is_not_a_run"]


def test_rogue_agent_exceeds_the_budgets(tmp_path):
    # Calls: the fourth attempt is denied, and denied calls count.
    tools = _tools(tmp_path / "calls", policy=Policy(Budget(max_calls=3)))
    compiled = tools.call("compile", prompt=PROMPT, reason="1")
    tools.call("validate", spec=compiled["spec"], reason="2")
    tools.call("validate", spec=compiled["spec"], reason="3")
    denied = tools.call("validate", spec=compiled["spec"], reason="4")
    assert denied["refused"] == "authority.budget"
    assert denied["sentence"] == render("authority.budget")
    assert "4 tool calls; the allowance is 3" in denied["message"]
    denied = tools.call("compile", prompt=PROMPT, reason="5")
    assert denied["refused"] == "authority.budget"
    assert [r["policy"].get("rule") for r in _trace(tools.trace.path)] == [
        None, None, None, "authority.budget", "authority.budget"]
    # Wall time: a clock the test advances.
    now = [0.0]
    clocked = Policy(Budget(max_wall_seconds=10.0), clock=lambda: now[0])
    tools = _tools(tmp_path / "wall", policy=clocked)
    compiled = tools.call("compile", prompt=PROMPT, reason="1")
    now[0] = 9.0
    assert "refused" not in tools.call("validate", spec=compiled["spec"], reason="2")
    now[0] = 11.0
    denied = tools.call("validate", spec=compiled["spec"], reason="3")
    assert denied["refused"] == "authority.budget" and "11 s elapsed" in denied["message"]
    # Re-samples per slot: drawing slot 0 a fourth time is denied.
    tools = _tools(tmp_path / "slots", policy=Policy(Budget(max_resamples_per_slot=3)))
    compiled = tools.call("compile", prompt=PROMPT, reason="1")
    tools.call("plan_campaign", spec=compiled["spec"], images=IMAGES,
               out=str(tmp_path / "slots" / "c"), reason="plan")
    for _ in range(3):
        assert "refused" not in tools.call("sample", campaign_id="c", n=1, start=0, reason="draw 0")
    denied = tools.call("sample", campaign_id="c", n=1, start=0, reason="draw 0 again")
    assert denied["refused"] == "authority.budget" and "re-sampled 4 times" in denied["message"]
    assert "refused" not in tools.call("sample", campaign_id="c", n=1, reason="the next slot")
    # The exception itself renders from the catalogue.
    with pytest.raises(Denial) as caught:
        Policy(Budget(max_calls=0)).check("compile", {})
    assert caught.value.explain()["rule"] == "authority.budget"


# -- the cooperative agent ------------------------------------------------------------------

def test_cooperative_agent_completes_a_tiny_headless_campaign_end_to_end(tmp_path):
    out = tmp_path / "demo"
    tools = _tools(out)
    outcome = Controller(tools, preview=2).run(Request(PROMPT, images=IMAGES))
    assert outcome.state == "done", outcome.sentence
    assert outcome.campaign_id == "demo" and outcome.yield_frames >= IMAGES
    assert outcome.sentence.startswith(f"Done: {outcome.yield_frames} verified frames of {IMAGES} in 2 case(s)")
    assert "labels only" in outcome.sentence
    assert Path(outcome.dataset_path, "annotations", "instances_train.json").is_file()
    record = json.loads((out / "campaign.json").read_text(encoding="utf-8"))
    assert record["state"] == "done" and record["images_target"] == IMAGES
    assert (out / "report.json").is_file() and (out / "ledger.jsonl").is_file()
    # The trace: every call a line, every line one sentence of reason, no denial.
    rows = _trace(out / "trace.jsonl")
    assert rows and all(set(r) == {"t", "tool", "input", "output", "reason", "policy"} for r in rows)
    assert all(r["policy"] == {"ok": True} for r in rows)
    assert all(r["reason"].strip().endswith(".") and r["reason"].count(". ") <= 1 for r in rows)
    tools_called = [r["tool"] for r in rows if r["tool"] != "controller"]
    assert tools_called[:4] == ["compile", "validate", "plan_campaign", "sample"]
    assert tools_called.count("run") == 3            # two slots, then the campaign to target
    assert tools_called.count("verify") == 2 and tools_called.count("render") == 2
    assert tools_called[-2:] == ["report", "export"]
    # Specs travel as digests in the trace; the token is the one validate minted.
    compile_row = next(r for r in rows if r["tool"] == "compile")
    validate_row = next(r for r in rows if r["tool"] == "validate")
    assert validate_row["input"]["spec"] == {"spec_digest": compile_row["output"]["spec_digest"]}
    token = validate_row["output"]["validation_token"]
    assert all(r["input"]["validation_token"] == token for r in rows
               if r["tool"] in ("run", "render", "export"))
    # The controller's decisions are in the file, one sentence each.
    decisions = [r["reason"] for r in rows if r["tool"] == "controller"]
    assert any(d.startswith("The plan needs about 2 case(s)") for d in decisions)
    assert sum(d.startswith("Case ") and "verified with" in d for d in decisions) == 2
    assert any(d.startswith("Yield ") and "coverage" in d for d in decisions)
    assert decisions[-1] == outcome.sentence and outcome.steps == decisions
    # The stated fields of every case are the compiled spec's, untouched.
    reference = _stated(flatten(compile_row["output"]["spec"])) if "value" in json.dumps(
        compile_row["output"]["spec"]) else None
    assert reference is None                          # the trace holds the digest, not the spec
    from core.scenario.spec import ScenarioSpec

    compiled = ScenarioSpec.from_dict(record["spec"]).to_dict()
    stated = {p: q for p, q in flatten(compiled).items() if q["source"] in ("user", "inferred")}
    ledger = [json.loads(l) for l in (out / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    verified = [r for r in ledger if r["status"] == "verified"]
    assert len(verified) == 2
    for row in verified:
        case = flatten(ScenarioSpec.read(Path(row["run_dir"]) / "spec.yaml").to_dict())
        assert {p: case[p] for p in stated} == stated
        assert {p for p, q in case.items() if q["source"] == "sampled"} >= {
            "randomization.cloud_cover", "randomization.hour_local"}
    # The verifier, read-only here: verification.json was written by the run stage.
    verdict = tools.call("verify", run_id=verified[0]["case_id"], reason="re-check")
    assert verdict["verdict"] == "pass" and verdict["failed"] == 0
    inspected = tools.call("inspect", run_id=verified[0]["case_id"], frame=0, reason="look")
    assert inspected["overlay_png"] is None and len(inspected["records"]) == 1
    assert inspected["note"].startswith("no pixels to overlay")
    report = tools.call("report", campaign_id="demo", reason="read")
    assert report["yield"]["frames_verified"] >= IMAGES and report["state"] == "done"
    assert set(report["realised_fields"]) >= {"cloud_cover", "hour_local"}


def test_the_controller_escalates_in_catalogue_language_and_runs_nothing(tmp_path):
    out = tmp_path / "bad"
    outcome = Controller(_tools(out)).run(Request(UNFLYABLE, images=10))
    assert outcome.state == "escalated" and outcome.rule == "airspeed.stall_margin"
    assert outcome.sentence == (
        "The scenario cannot run as stated: A speed of 40 knots is too slow for this "
        "aircraft to keep flying; it needs at least 185.194 knots. (airspeed.stall_margin)")
    assert not (out / "campaign.json").exists() and not (out / "ledger.jsonl").exists()
    rows = _trace(out / "trace.jsonl")
    assert [r["tool"] for r in rows] == ["compile", "controller"]
    assert rows[-1]["reason"] == "Escalate: " + outcome.sentence
    # A question is escalated as a question, with how to answer it.
    asked = Controller(_tools(tmp_path / "q")).run(
        Request("film the a320 at 3000 m for 5 seconds", images=10))
    assert asked.state == "escalated"
    assert asked.sentence.startswith("The request needs an answer before anything runs: "
                                     "Which point of view should the camera take?")
    assert "--answer camera_view=<choice>" in asked.sentence
    # Answered, the same request compiles without a question.
    tools = _tools(tmp_path / "a")
    compiled = tools.call("compile", prompt="film the a320 at 3000 m for 5 seconds",
                          answers=[{"id": "camera_view", "answer": "chase"}], reason="answered")
    assert compiled["questions"] == [] and compiled["refusals"] == []


def test_the_controller_resamples_only_system_chosen_fields_and_escalates_by_name(tmp_path):
    out = tmp_path / "inf"
    tools = _tools(out, policy=Policy(Budget(max_resamples_per_slot=2)))
    outcome = Controller(tools, preview=1).run(
        Request(FAST, images=50, policy=INFEASIBLE_POLICY))
    assert outcome.state == "escalated" and outcome.rule == "campaign.target_unreachable"
    assert outcome.sentence.startswith("3 slots in a row were refused")
    assert render("campaign.target_unreachable") in outcome.sentence
    rows = _trace(out / "trace.jsonl")
    resamples = [r for r in rows if r["tool"] == "controller"
                 and r["reason"].startswith("Slot ") and "randomization.infeasible" in r["reason"]]
    assert [r["input"]["slot"] for r in resamples] == [0, 1, 2]
    assert all("re-draws only system-chosen leaves and every stated value stays" in r["reason"]
               for r in resamples)
    assert [r["tool"] for r in rows if r["tool"] == "sample"] == ["sample"] * 3
    assert not any(r["tool"] == "run" for r in rows)            # nothing ran
    # Every refused draw moved nothing the person stated: the record's spec
    # keeps the compiled provenance and the policy is a recorded plan edit.
    record = json.loads((out / "campaign.json").read_text(encoding="utf-8"))
    flat = flatten(record["spec"])
    assert flat["initial.airspeed"] == {"value": 280.0, "source": "user", "from": "280 kt"}
    assert flat["randomization.policy"]["source"] == "derived"
    assert flat["randomization.policy"]["from"] == "policy chosen by the assistant"
    ledger = [json.loads(l) for l in (out / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in ledger] == ["refused"] * 3
    assert all(r["refusals"] == ["randomization.infeasible"] for r in ledger)
    assert all(set(a["sampled_values"]) == {"aircraft"} for r in ledger
               for a in r["refused_attempts"])           # only the policy's leaf was drawn


def test_the_agent_cli_runs_a_request_and_exits_by_outcome(tmp_path, capsys):
    from flightsim.agent import main

    assert main([PROMPT, "--images", "0", "--out", str(tmp_path / "z")]) == 2
    assert "REFUSED -- campaign.arguments" in capsys.readouterr().out
    assert main([PROMPT, "--images", "5", "--out", str(tmp_path / "z"), "--policy", "{"]) == 2
    assert "not JSON" in capsys.readouterr().out
    assert main([UNFLYABLE, "--images", "5", "--out", str(tmp_path / "bad")]) == 1
    printed = capsys.readouterr().out
    assert "escalated: The scenario cannot run as stated" in printed
    assert main([PROMPT, "--images", str(IMAGES), "--out", str(tmp_path / "ok"),
                 "--preview", "1", "--json"]) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["state"] == "done" and outcome["yield_frames"] >= IMAGES
    assert Path(outcome["trace_path"]).is_file()
