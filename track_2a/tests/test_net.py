from gegenprobe.net import quote_url


def test_quote_url_encodes_raw_spaces_and_umlauts_once():
    u = "https://www.stadt-zuerich.ch/docs/Antwort Stadtrat Zürich.pdf?x=a b"
    q = quote_url(u)
    assert " " not in q and "ü" not in q
    assert quote_url(q) == q  # idempotent on already-encoded URLs


def test_quote_url_keeps_query_structure():
    u = "https://www.rrgr-service.apps.be.ch/api/gr/instances/x/render?gnumber=2024.RRGR.91&lang=de"
    assert quote_url(u) == u
