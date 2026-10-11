from gegenprobe.net import quote_url


def test_quote_url_encodes_raw_spaces_and_umlauts_once():
    u = "https://www.stadt-zuerich.ch/docs/Antwort Stadtrat Zürich.pdf?x=a b"
    q = quote_url(u)
    assert " " not in q and "ü" not in q
    assert quote_url(q) == q  # idempotent on already-encoded URLs


def test_quote_url_keeps_query_structure():
    u = "https://www.rrgr-service.apps.be.ch/api/gr/instances/x/render?gnumber=2024.RRGR.91&lang=de"
    assert quote_url(u) == u


# ---- operations hardening: local exports, robots.txt fail-closed, size caps
import gzip  # noqa: E402
import io  # noqa: E402
import urllib.error  # noqa: E402

import pytest  # noqa: E402

from gegenprobe import net  # noqa: E402


@pytest.fixture
def fresh_net(monkeypatch):
    monkeypatch.setattr(net, "_robots", {})
    monkeypatch.setattr(net, "_robots_note", {})
    monkeypatch.setattr(net, "_robots_lenient", {})
    monkeypatch.setattr(net, "_wait", lambda host: None)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    return net


def _http_error(code):
    return urllib.error.HTTPError("https://x.example/robots.txt", code, "x", {}, io.BytesIO(b""))


def test_local_exports_maps_only_the_exports_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_EXPORTS_DIR", str(tmp_path))
    assert net.local_exports(net.EXPORTS_PREFIX + "docs/docs_BE.ndjson.gz") == (tmp_path / "docs/docs_BE.ndjson.gz").as_uri()
    assert net.local_exports("https://ogd.parl.apps.be.ch/data/dokument.csv").startswith("https://")
    monkeypatch.delenv("GP_EXPORTS_DIR")
    assert net.local_exports(net.EXPORTS_PREFIX + "index.json") == net.EXPORTS_PREFIX + "index.json"


def test_local_exports_are_read_without_network(monkeypatch, tmp_path, fresh_net):
    (tmp_path / "docs").mkdir()
    (tmp_path / "index.json").write_text('{"files": []}')
    with gzip.open(tmp_path / "docs" / "docs_XX.ndjson.gz", "wt") as f:
        f.write('{"id": 1}\n{"id": 2}\n')
    monkeypatch.setenv("GP_EXPORTS_DIR", str(tmp_path))
    monkeypatch.setattr(net, "allowed", lambda url: pytest.fail(f"network path taken for {url}"))
    assert net.get(net.EXPORTS_PREFIX + "index.json") == b'{"files": []}'
    assert list(net.stream_ndjson_gz(net.EXPORTS_PREFIX + "docs/docs_XX.ndjson.gz")) == ['{"id": 1}\n', '{"id": 2}\n']


@pytest.mark.parametrize("failure", [urllib.error.URLError("dns"), TimeoutError(), _http_error(503), _http_error(429)])
def test_robots_unreadable_fails_closed(monkeypatch, fresh_net, failure):
    # RFC 9309 2.3.1.4 "unreachable" (5xx, network; 429 = back off): complete disallow, typed robots_unreachable
    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(net.urllib.request, "urlopen", boom)
    assert not net.allowed("https://x.example/doc.pdf")
    assert "https://x.example" in net.robots_report()
    with pytest.raises(net.Disallowed, match="fail-closed") as e:
        net.open_url("https://x.example/doc.pdf")
    assert e.value.kind == "robots_unreachable"


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 451])
def test_robots_4xx_means_no_restrictions(monkeypatch, fresh_net, code):
    # RFC 9309 2.3.1.3 "unavailable": any 4xx on robots.txt (Fribourg's api.fr.ch answers 403) -> every path allowed
    def missing(*a, **k):
        raise _http_error(code)

    monkeypatch.setattr(net.urllib.request, "urlopen", missing)
    assert net.allowed("https://x.example/doc.pdf") and net.robots_report() == {}
    assert ("https://x.example" in net.robots_lenient()) == (code not in (404, 410))


def test_robots_404_means_allowed(monkeypatch, fresh_net):
    def missing(*a, **k):
        raise _http_error(404)

    monkeypatch.setattr(net.urllib.request, "urlopen", missing)
    assert net.allowed("https://x.example/doc.pdf") and net.robots_report() == {}


def test_robots_transient_5xx_is_retried_once(monkeypatch, fresh_net):
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(502)
        return Resp(b"User-agent: *\nDisallow: /private/\n")

    monkeypatch.setattr(net.urllib.request, "urlopen", flaky)
    assert net.allowed("https://x.example/public/a.pdf") and not net.allowed("https://x.example/private/a.pdf")
    assert len(calls) == 2
    with pytest.raises(net.Disallowed, match="disallows this path") as e:  # a real Disallow: typed robots_disallowed
        net.open_url("https://x.example/private/a.pdf")
    assert e.value.kind == "robots_disallowed" and net.robots_report() == {}


def test_api_v1_is_refused():
    assert not net.allowed("https://api.openparldata.ch/v1/affairs")


def test_get_refuses_bodies_above_the_cap(tmp_path):
    p = tmp_path / "big.bin"
    p.write_bytes(b"x" * 5000)
    assert net.get(p.as_uri(), max_bytes=5000) == b"x" * 5000
    with pytest.raises(net.TooLarge) as e:
        net.get(p.as_uri(), max_bytes=4999)
    assert e.value.kind == "too_large"


def test_user_agent_is_configurable_and_has_no_personal_data():
    import subprocess
    import sys

    code = "from gegenprobe import net; print(net.UA)"
    env = {"PYTHONPATH": "src", "GP_USER_AGENT": "opd-gegenprobe/1.0"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "opd-gegenprobe/1.0"
    assert net.UA == "hackapertus-research/0.1" or "GP_USER_AGENT" in __import__("os").environ
