"""Report figures, generated from committed results files only (no hand-typed numbers). Dev-only: needs matplotlib
(`pip install -e .[report]`); the judges' runtime does not.

    python -m report.figures            -> docs/figures/fig{1..5}_*.{png,svg} + results/report/figure_numbers.json

Palette: the dataviz reference instance, validated with its validator (categorical slots 1-3 blue/orange/aqua pass
all-pairs CVD and normal-vision floors; the blue ordinal ramp 600/400/250 passes --ordinal). Aqua is below 3:1 on the
surface, so every aqua mark carries a direct label. Derived numbers that the README prints (sums of results fields) are
written to results/report/figure_numbers.json so claims.tsv can trace them.
"""
from __future__ import annotations

import csv
import gzip
import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from gegenprobe.paths import DATA, DOCS, RESULTS  # noqa: E402

OUT = DOCS / "figures"
NUM = RESULTS / "report" / "figure_numbers.json"

SURFACE = "#ffffff"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"          # categorical slots 1-3 (validated all-pairs)
RAMP = {"600": "#184f95", "400": "#3987e5", "250": "#86b6ef"}   # ordinal blue (validated --ordinal)
GRAY, GRAY_LIGHT = "#a8a6a0", "#dcdad4"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": GRAY, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "svg.fonttype": "none",
})


def j(path: str):
    return json.loads((RESULTS / path).read_text())


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def fmt(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------- numbers
def numbers() -> dict:
    s = j("census/summary.json")
    r = j("repair/summary.json")
    be = j("repair/be_list_summary.json")["counts"]
    pl = j("repair/be_placement.json")["total"]
    cu = r["precision"]["che_curia"]
    nat = s["national"]
    dec = s["gap_prime_decomposition"]
    ocr_non_be = r["by_action"]["ocr"] - r["by_body"].get("BE", {}).get("ocr", 0)
    other_rest = dec["other_doc_present_no_text"] - r["by_action"]["retype_oral"] - ocr_non_be
    che_rest = dec["CHE"] - cu["substantive"][0]
    gap = {
        "needs_adapters": dec["other_no_answer_doc"],
        "be_relink": be["relink"],
        "ocr": ocr_non_be,
        "vs_oral": r["by_action"]["retype_oral"],
        "agenda_join": s["agenda_rejoin_in_gap"],
        "che_formula_or_nothing": che_rest,
        "be_fetch": be["fetch"],
        "other_doc_no_text_rest": other_rest,
        "che_curia_substantive": cu["substantive"][0],
        "be_no_source": be["no_source_answer"],
    }
    assert sum(gap.values()) == nat["gap"], (sum(gap.values()), nat["gap"])
    linked_after = pl["attached"] + pl["via_agenda"] + pl["orphan_uid"]
    out = dict(
        written_answer_affairs=nat["ev_answer"],
        text_present=nat["ev_answer"] - nat["gap"],
        gap=nat["gap"],
        gap_parts=gap,
        repairable_deterministic=gap["agenda_join"] + gap["be_relink"] + gap["be_fetch"] + gap["che_curia_substantive"],
        be_source_answered=pl["source_answered"],
        be_linked_before=pl["attached"],
        be_linked_after_joins=linked_after,
        be_linked_after_share=linked_after / pl["source_answered"],
        be_linked_before_share=pl["attached"] / pl["source_answered"],
        be_absent=pl["absent"],
    )
    NUM.parent.mkdir(parents=True, exist_ok=True)
    NUM.write_text(json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------- fig 1: funnel with typed causes
def fig1(n: dict) -> None:
    g = n["gap_parts"]
    cats = [  # (label, value, colour, group)
        ("No answer document in OPD: needs a per-body source adapter", g["needs_adapters"], GRAY, "none"),
        ("BE: relink the parentless OPD copy by canton uid", g["be_relink"], BLUE, "det"),
        ("Image-only answer scans: OCR (deu+fra+ita)", g["ocr"], AQUA, "ocr"),
        ("VS: retype as oral answer (not missing)", g["vs_oral"], ORANGE, "oral"),
        ("Answer filed under an agenda item: in-corpus join", g["agenda_join"], BLUE, "det"),
        ("CHE: Curia Vista has only a formula or nothing", g["che_formula_or_nothing"], GRAY_LIGHT, "none"),
        ("BE: fetch the answer from the canton", g["be_fetch"], BLUE, "det"),
        ("Other: answer document without text", g["other_doc_no_text_rest"], GRAY_LIGHT, "none"),
        ("CHE: substantive answer in Curia Vista", g["che_curia_substantive"], BLUE, "det"),
        ("BE: no answer at the canton either", g["be_no_source"], GRAY_LIGHT, "none"),
    ]
    fig, (a0, a1) = plt.subplots(2, 1, figsize=(7.2, 4.6), gridspec_kw=dict(height_ratios=[1, 5.2], hspace=0.55))
    # context bar
    a0.barh([0], [n["text_present"]], color=GRAY_LIGHT, height=0.6, edgecolor=SURFACE, linewidth=2)
    a0.barh([0], [n["gap"]], left=[n["text_present"]], color=ORANGE, height=0.6, edgecolor=SURFACE, linewidth=2)
    a0.set_xlim(0, n["written_answer_affairs"])
    a0.set_yticks([])
    a0.spines["left"].set_visible(False)
    a0.text(n["text_present"] / 2, 0, f"answer text in OPD  {fmt(n['text_present'])}", ha="center", va="center", color=INK)
    a0.text(n["text_present"] + n["gap"] / 2, 0, fmt(n["gap"]), ha="center", va="center", color=INK, fontweight="bold")
    a0.set_title(f"{fmt(n['written_answer_affairs'])} interventions with a written-answer event; "
                 f"{fmt(n['gap'])} have no answer text in OPD", loc="left", color=INK, fontsize=9)
    a0.tick_params(axis="x", labelsize=7)
    a0.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(int(v))))
    # decomposition
    y = list(range(len(cats)))[::-1]
    a1.barh(y, [c[1] for c in cats], color=[c[2] for c in cats], height=0.62, edgecolor=SURFACE, linewidth=1)
    for yi, (_lab, v, _, _) in zip(y, cats):
        a1.text(v + 120, yi, fmt(v), va="center", color=INK, fontsize=7.5)
    a1.set_yticks(y, [c[0] for c in cats], fontsize=7.5)
    a1.set_xlim(0, max(c[1] for c in cats) * 1.12)
    a1.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(int(v))))
    a1.tick_params(axis="x", labelsize=7)
    a1.set_title(f"Where the {fmt(n['gap'])} go: typed cause and repair route", loc="left", color=INK, fontsize=9)
    a1.legend(handles=[Patch(color=BLUE, label="deterministic repair route"), Patch(color=AQUA, label="OCR route"),
                       Patch(color=ORANGE, label="not missing: oral answer"), Patch(color=GRAY, label="no measured route")],
              loc="lower right", frameon=False, fontsize=7)
    save(fig, "fig1_funnel")


# ---------------------------------------------------------------- fig 2: feasibility matrix
STATUS = [("metadata", RAMP["600"], "in OPD metadata"), ("mixed", RAMP["400"], "metadata for part of the affairs"),
          ("pdf", RAMP["250"], "only in the PDF"), ("no_source", ORANGE, "no source in OPD"),
          ("n/a", GRAY_LIGHT, "not applicable / too few affairs")]


def _bodies() -> dict:
    with gzip.open(DATA / "census" / "bodies.tsv.gz", "rb") as f:
        rows = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        return {r["key"]: r for r in rows}


def fig2(n_communes: int = 13) -> dict:
    m = list(csv.DictReader(open(RESULTS / "census" / "matrix.csv", encoding="utf-8")))
    meta = j("census/matrix.json")
    B = _bodies()
    size = {r["body"]: int(r["n"]) for r in m if r["field"] == "type"}
    level = {"country": 0, "canton": 1, "city": 2, "municipality": 2}
    lang = {"DE": 0, "FR": 1, "IT": 2}
    upper = [b for b in size if level.get(B.get(b, {}).get("type"), 2) < 2]
    communes = sorted((b for b in size if b not in upper), key=lambda b: -size[b])[:n_communes]
    key = lambda b: (level.get(B[b]["type"], 2), lang.get(B[b]["lang"], 3), -size[b])  # noqa: E731
    cols = sorted(upper, key=key) + sorted(communes, key=key)
    tier_order = {"feasible": 0, "partial": 1, "fundamentally different": 2}
    fields = sorted(meta["fields"], key=lambda f: (tier_order.get(meta["fields"][f]["tier"], 3), f))
    st = {(r["field"], r["body"]): r["status"] for r in m}
    cmap = {k: c for k, c, _ in STATUS}
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    for yi, f in enumerate(fields):
        for xi, b in enumerate(cols):
            ax.add_patch(plt.Rectangle((xi, yi), 0.92, 0.88, color=cmap.get(st.get((f, b), "n/a"), GRAY_LIGHT), lw=0))
    ax.set_xlim(0, len(cols))
    ax.set_ylim(len(fields), 0)
    def lab(b):
        nm = B[b]["name"] if B[b]["type"] in ("city", "municipality") else b
        return nm[:14]
    ax.set_xticks([i + 0.46 for i in range(len(cols))], [lab(b) for b in cols], rotation=90, fontsize=5.6)
    ax.set_yticks([i + 0.44 for i in range(len(fields))],
                  [f"{f.replace('_', ' ')}  [{meta['fields'][f]['tier']}]" for f in fields], fontsize=6.6)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    split = len([b for b in cols if b in upper])
    ax.axvline(split - 0.04, color=INK2, lw=0.8)
    ax.text(split / 2, -0.6, "federal, Liechtenstein, cantons", ha="center", fontsize=6.6, color=INK2)
    ax.text(split + (len(cols) - split) / 2, -0.6, f"largest {n_communes} communal parliaments", ha="center",
            fontsize=6.6, color=INK2)
    ax.legend(handles=[Patch(color=c, label=t) for _, c, t in STATUS], loc="upper center", bbox_to_anchor=(0.5, -0.2),
              ncol=5, frameon=False, fontsize=6.4)
    ax.set_title(f"Where each schema field comes from, per parliament ({len(cols)} of {meta['n_bodies']} bodies; "
                 f"all {meta['n_bodies']} in results/census/matrix.csv)", loc="left", fontsize=8.5, color=INK, pad=14)
    save(fig, "fig2_matrix")
    return dict(matrix_columns=len(cols), matrix_bodies=meta["n_bodies"], matrix_fields=len(fields))


# ---------------------------------------------------------------- fig 3: BE before / after
def fig3(n: dict) -> None:
    pl = j("repair/be_placement.json")["total"]
    tot = pl["source_answered"]
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    before = [("attached to the affair", pl["attached"], BLUE), ("under an agenda item", pl["via_agenda"], AQUA),
              ("parentless, canton uid", pl["orphan_uid"], ORANGE), ("absent", pl["absent"], GRAY)]
    after = [("linked to the affair (229 + 527 + 2,638)", n["be_linked_after_joins"], BLUE), ("absent", pl["absent"], GRAY)]
    for yi, segs in ((1, before), (0, after)):
        left = 0
        for lab, v, c in segs:
            ax.barh([yi], [v], left=[left], color=c, height=0.55, edgecolor=SURFACE, linewidth=2)
            if v / tot > 0.5:
                ax.text(left + v / 2, yi, f"{lab}  {fmt(v)}", ha="center", va="center", fontsize=7, color=SURFACE if c == BLUE
                        else INK)
            left += v
    ax.text(tot, 0.33, f"absent {fmt(pl['absent'])}: fetch from the canton", ha="right", va="bottom", fontsize=6.5, color=INK2)
    ax.legend(handles=[Patch(color=c, label=f"{lab} {fmt(v)}") for lab, v, c in before], loc="upper center",
              bbox_to_anchor=(0.5, -0.32), ncol=4, frameon=False, fontsize=6.6)
    ax.set_yticks([1, 0], ["OPD today", "after the two joins"], fontsize=7.5)
    ax.set_xlim(0, tot)
    ax.set_ylim(-0.45, 1.45)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(int(v))))
    ax.tick_params(axis="x", labelsize=7)
    ax.set_title(f"Bern: {fmt(tot)} answers the canton publishes; linked in OPD {n['be_linked_before_share']:.1%} → "
                 f"{n['be_linked_after_share']:.1%} by deterministic joins", loc="left", fontsize=8.5, color=INK)
    save(fig, "fig3_be_before_after")


# ---------------------------------------------------------------- fig 4: the naive converter vs the corpus
def fig4() -> dict:
    nv = j("convert/spike_replay.json")["naive"]
    mg = json.loads((DATA / "convert" / "spike_margins.json").read_text())["naive"]["round7_dwq_8b"]
    sample = j("schema/samples/be_2024_RRGR_91.json")
    item = next(x for x in mg if str(x["id"]) == str(sample["ref"]["opd_id"]))
    gen = json.loads(item["arms"]["null"]["gen"])
    num = _find_quote(sample, '"quote": "879/2024"')["answer_quote"]
    answered = next(d["date"]["value"] for d in sample["dates"] if d["role"] == "answered")
    uid = next(q["answer_doc"] for q in sample["qa"] if q["link_status"] == "parentless").split(":", 1)[1]
    relinked = next(d["doc_id"].split(":", 1)[1] for d in sample["documents"]
                    if d["source"] == "opd" and uid in (d.get("url") or ""))
    real = _find_quote(sample, '"quote": "28. August 2024"')["answer_quote"]
    bars = [("8B 4-bit, local\nplain prompt", nv["round7_dwq_8b|plain"]),
            ("8B 4-bit, local\nnull allowed", nv["round7_dwq_8b|null"]),
            ("70B, Public AI\nplain prompt", nv["live_publicai_70b_name|plain"]),
            ("70B, Public AI\nnull allowed", nv["live_publicai_70b_name|null"])]
    fig = plt.figure(figsize=(7.2, 2.9))
    a = fig.add_axes([0.06, 0.3, 0.42, 0.55])
    xs = range(len(bars))
    vals = [b[1]["invented_on_null_docs"] for b in bars]
    a.bar(xs, vals, color=BLUE, width=0.55)
    for x, (_lab, d) in zip(xs, bars):
        a.text(x, d["invented_on_null_docs"] + 0.3, f"{d['invented_on_null_docs']}/{d['n_gold_null']}", ha="center", fontsize=7.5)
        if d["invented_passing_receipt_check"]:
            a.bar([x], [d["invented_passing_receipt_check"]], color=BLUE, width=0.55, hatch="////", edgecolor=SURFACE, lw=0)
    a.set_xticks(list(xs), [b[0] for b in bars], fontsize=6.4)
    hatch_label = "date backed by a quote that passes\na naive verbatim check"
    a.legend(handles=[Patch(facecolor=BLUE, hatch="////", edgecolor=SURFACE, label=hatch_label)],
             loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False, fontsize=6)
    a.set_ylim(0, 16.5)
    a.set_yticks([0, 5, 10, 15])
    a.tick_params(axis="y", labelsize=7)
    a.set_title("Free generation: answer date given on\n15 BE interpellations that have no answer", loc="left", fontsize=8,
                color=INK)
    t = fig.add_axes([0.53, 0.05, 0.46, 0.85])
    t.axis("off")
    lines = [
        ("2024.RRGR.91 (BE interpellation), question document only", INK, "bold"),
        ("Naive converter, null-allowed prompt, Apertus 8B:", INK2, "normal"),
        (f'  date {gen["antwort_datum"]}, "{gen["rrb_nr"]}"', ORANGE, "bold"),
        (f'  receipt quoted: "{gen["beleg"]}" (not in the document)', INK2, "normal"),
        ("Gegenprobe: answer is unlinked, not absent.", INK2, "normal"),
        (f"  OPD parentless doc {relinked}, relinked by canton uid:", INK2, "normal"),
        (f'  RRB-Nr. "{num}", decision date "{real}" (verbatim spans, p. 1)', BLUE, "bold"),
        (f"  = OPD 'Beantwortet' event date ({answered})", INK2, "normal"),
    ]
    yy = 0.95
    for txt, c, w in lines:
        t.text(0, yy, txt, fontsize=7, color=c, fontweight=w, va="top", family="DejaVu Sans")
        yy -= 0.12
    save(fig, "fig4_naive_contrast")
    return dict(naive_example_date=gen["antwort_datum"], naive_example_rrb=gen["rrb_nr"])


def _find_quote(sample: dict, needle: str) -> dict:
    s = json.dumps(sample, ensure_ascii=False)
    i = s.find(needle)
    assert i >= 0, needle
    q0 = i + len('"quote": "')
    return dict(answer_quote=s[q0:s.find('"', q0)])


# ---------------------------------------------------------------- fig 5: held-out scoreboard (filled by the integrator)
def fig5() -> bool:
    files = sorted((RESULTS / "eval").glob("heldout__*.json"))
    if not files:
        return False
    print(f"fig5: {len(files)} held-out results file(s) present; scoreboard figure not implemented yet (integrator)")
    return False


def main() -> None:
    n = numbers()
    fig1(n)
    extra = fig2()
    fig3(n)
    extra.update(fig4())
    d = json.loads(NUM.read_text())
    d.update(extra)
    NUM.write_text(json.dumps(d, indent=1))
    fig5()
    print(json.dumps({k: v for k, v in d.items() if k != "gap_parts"}, indent=1))


if __name__ == "__main__":
    main()
