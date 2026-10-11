"""Nightly job robustness: atomic outbox and state writes, a corrupt outbox or state file is quarantined and
reported instead of failing every night, and the offline fixture smoke run that CI also runs inside the Docker image."""
import json
import os

from gegenprobe.monitor import nightly, notify, smoke


def test_outbox_write_is_atomic_and_leaves_no_temp_files(tmp_path, monkeypatch):
    box = tmp_path / "nightly" / "outbox.json"
    notify.write_outbox(box, [dict(kind="a", body="ZH")])
    assert json.loads(box.read_text()) == [dict(kind="a", body="ZH")]

    def crash(src, dst):  # the rename never happens: the old outbox must survive intact
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", crash)
    try:
        notify.write_outbox(box, [dict(kind="b", body="BE")])
    except OSError:
        pass
    assert json.loads(box.read_text()) == [dict(kind="a", body="ZH")]
    assert sorted(p.name for p in box.parent.iterdir()) == ["outbox.json"]


def test_corrupt_outbox_is_quarantined_and_reported(tmp_path):
    box = tmp_path / "outbox.json"
    assert notify.read_outbox(box) == ([], [])
    box.write_text('[{"kind": "linking_rate_drop", "body": "ZH"')
    pending, al = notify.read_outbox(box)
    assert pending == [] and [a["kind"] for a in al] == ["outbox_corrupt"]
    assert not box.exists() and len(list(tmp_path.glob("outbox.json.corrupt-*"))) == 1
    box.write_text('{"not": "a list"}')
    assert [a["kind"] for a in notify.read_outbox(box)[1]] == ["outbox_corrupt"]
    box.write_text(json.dumps([dict(kind="x", body="BE")]))
    assert notify.read_outbox(box) == ([dict(kind="x", body="BE")], [])


def test_corrupt_state_is_quarantined_and_the_night_runs_as_a_first_night(tmp_path):
    st = tmp_path / "state.json"
    st.write_text("{trunc")
    state, al = nightly.read_state(st)
    assert state == {} and al[0]["kind"] == "state_corrupt" and not st.exists()
    st.write_text(json.dumps(dict(rates={})))
    assert nightly.read_state(st) == (dict(rates={}), [])


def test_offline_nights_on_fixture_exports(tmp_path):
    assert smoke.smoke(tmp_path) == []


def test_local_exports_night_reads_a_read_only_exports_dir_and_sends_nothing(tmp_path):
    """The "Inside OPD" setup (GP_EXPORTS_DIR): a network-mode night whose exports all come from a read-only directory in
    OPD's layout; nothing goes over the network (canton tables from GP_BE_OGD_LOCAL, BE row checks to a .invalid host).
    CI runs the same night inside the image with the Docker unit's --env-file and read-only --mount (job nightly-smoke)."""
    try:
        assert smoke.local_exports(tmp_path) == []
        ex = tmp_path / "exports"
        assert (ex / "index.json").exists() and not os.access(ex / "affairs.ndjson.gz", os.W_OK) or os.geteuid() == 0
    finally:
        for f in [tmp_path / "exports", *(tmp_path / "exports").rglob("*")]:
            f.chmod(0o755 if f.is_dir() else 0o644)
