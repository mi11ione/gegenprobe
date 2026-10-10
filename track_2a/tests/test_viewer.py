"""The committed evidence viewer: renders from site/data.json alone, shows every view's data, and carries document text
only as short excerpt windows (never full texts)."""
import json
import re

from gegenprobe.viewer.__main__ import SITE, render
from gegenprobe.viewer.data import EXCERPT_MAX


def _texts(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "t" and isinstance(v, str):
                out.append(v)
            else:
                _texts(v, out)
    elif isinstance(o, list):
        for v in o:
            _texts(v, out)
    return out


def test_committed_site_has_no_full_texts():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    assert all("text" not in doc for doc in d["documents"]), "full page texts must never be committed"
    ex = _texts(d["documents"], [])
    assert ex and max(map(len, ex)) <= EXCERPT_MAX + 20


def test_every_view_has_data():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    assert len(d["documents"]) == 154
    assert len(d["parliaments"]["rows"]) == 89 and len(d["parliaments"]["fields"]) == 17
    ev = d["evaluation"]
    assert {"rules", "pointer", "cascade", "naive_plain", "naive_null"} <= set(ev["arms"])
    assert {"H1", "H2", "H3", "H4"} <= set(ev["hypotheses"])
    assert d["headline"]["gap"] == 16749


def test_render_is_self_contained(tmp_path):
    p = render(json.loads((SITE / "data.json").read_text(encoding="utf-8")), tmp_path)
    html = p.read_text(encoding="utf-8")
    assert "/*DATA*/" not in html
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    assert srcs == [], "no external scripts"
    blob = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    json.loads(blob.replace("<\\/", "</"))
