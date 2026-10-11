"""`make run` result line (src/gegenprobe/run.py): a PASS names the steps that skipped, and the P1 Apertus replay
coverage is printed (J5, round 12). No network, no model: the report dicts are built by hand."""
from gegenprobe import run


def _report(online, **status):
    steps = {"model": dict(status="SKIP")}
    for name, _, _ in run.STEPS:
        steps[name] = dict(status=status.get(name, "PASS"))
    return dict(online=online, secs=868.0, steps=steps)


def test_offline_pass_names_the_skipped_steps():
    r = _report(False, convert="SKIP", rederive="SKIP", rederive_apertus="SKIP")
    assert run.result_line(r) == ("RESULT PASS (offline: 3 steps skipped: convert, rederive, rederive_apertus) "
                                  "in 868.0 s")
    assert run.coverage_line(r).startswith("Apertus replay: P1 0/154 decisions re-derived from the model cache (offline)")


def test_online_pass_without_skips_is_plain():
    r = _report(True)
    assert run.result_line(r) == "RESULT PASS in 868.0 s"


def test_online_skip_is_named_without_offline_and_fail_wins():
    r = _report(True, rederive="SKIP", census="FAIL")
    line = run.result_line(r)
    assert line.startswith("RESULT FAIL (1 step skipped: rederive) in 868.0 s") and line.endswith("failing: census")


def test_p1_coverage_from_the_rederive_apertus_step():
    r = _report(True, rederive_apertus="WARN")
    r["steps"]["rederive_apertus"]["coverage"] = {
        "P1 held-out": dict(n=154, rederived=132, match=132, cache_miss=22, unreachable=0, not_reached_budget=0),
        "P2 unseen": dict(n=62, rederived=54, match=54, cache_miss=0, unreachable=8, not_reached_budget=0)}
    assert run.coverage_line(r) == ("Apertus replay: P1 132/154 decisions re-derived from the model cache, 132 match "
                                    "(22 cache misses); P2 54/62, 54 match")
    assert run.replay_coverage(r)["sets"]["P1 held-out"]["rederived"] == 132


def test_rederive_apertus_reports_coverage_offline_skip():
    from eval import replay_all
    res = replay_all.main_rederive({"online": False})
    assert res["status"] == "SKIP" and "coverage" not in res
