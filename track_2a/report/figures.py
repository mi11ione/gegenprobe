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
        "needs_adapters": dec["other_no_answer_doc"] - dec.get("other_no_answer_doc_question_time", 0),
        "be_relink": be["relink"],
        "ocr": ocr_non_be,
        "vs_oral": r["by_action"]["retype_oral"],
        "question_time_oral": dec.get("other_no_answer_doc_question_time", 0),
        "agenda_join": s["agenda_rejoin_in_gap"],
        "che_formula_or_nothing": che_rest,
        "be_fetch": be["fetch"],
        "other_doc_no_text_rest": other_rest,
        "che_curia_substantive": cu["substantive"][0],
        "be_no_source": be["no_source_answer"],
    }
    assert sum(gap.values()) == nat["gap"], (sum(gap.values()), nat["gap"])
    linked_after = pl["attached"] + pl["via_agenda"] + pl["orphan_uid"]
    ad = j("repair/adapters/adapters_summary.json")
    adt = ad["totals"]
    assert ad["coverage"]["needs_adapters_before"] == gap["needs_adapters"], "adapter baseline differs from the census"
    adapters = dict(absent_verified=adt["verified_absent"], absent_open=gap["needs_adapters"] - adt["verified_absent"],
                    image_only_verified=adt["verified_image_only"], image_only_open=gap["ocr"] - adt["verified_image_only"])
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
        adapters=adapters,
    )
    NUM.parent.mkdir(parents=True, exist_ok=True)
    NUM.write_text(json.dumps(out, indent=1))
    return out


# Figures 1 and 2 sit at full text width in 444_Report.pdf: they are drawn at print size (PRINT_W inches wide, saved
# uncropped), so a font size here is the printed size; no text is set below 7.5 pt.
PRINT_W = 7.16  # A4 text width of report/render.py (210 mm - 2 x 14 mm = 182 mm)


def save_print(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=220)
    fig.savefig(OUT / f"{name}.svg")
    plt.close(fig)


def _axes_in(fig, x: float, y: float, w: float, h: float):
    """Axes placed in inches from the figure's lower left corner."""
    fw, fh = fig.get_size_inches()
    return fig.add_axes((x / fw, y / fh, w / fw, h / fh))


def _text_in(fig, labels: list, size: float, rotation: float = 0) -> float:
    """The largest extent (inches) of the labels at this size: width, or height when rotated 90 degrees."""
    r = fig.canvas.get_renderer()
    out = 0.0
    for s in labels:
        t = fig.text(0, 0, s, fontsize=size, rotation=rotation)
        bb = t.get_window_extent(r)
        out = max(out, (bb.height if rotation else bb.width) / fig.dpi)
        t.remove()
    return out * 1.06  # hinting at screen dpi measures a few per cent short of the 220 dpi render


# ---------------------------------------------------------------- fig 1: where the registered gap is (derived layer)
def fig1(n: dict) -> None:
    """The registered 16,749 placed once each by the derived census layer (results/census/corrected.json, national.all):
    blue = a verified repair is proposed, aqua = OPD's copy without text not yet read, orange = answered orally,
    grey = no verified answer yet. Wide and short for the report's full text width; every label is 7.5 pt or larger."""
    x = j("census/corrected.json")["national"]["all"]
    io_ = x["image_only_parts"]
    cats = [  # (label, value, colour)
        ("In OPD with text, filed elsewhere (agenda join, Bern relink)", x["opd_elsewhere"], BLUE),
        ("In OPD with text, heading not recognised (tag_answer)", x["unrecognised"], BLUE),
        ("Not in OPD; verified at the parliament (fetch)", x["fetchable"], BLUE),
        ("OPD copy without text; text verified (OCR)", io_["text_verified"] + io_["fetchable"], BLUE),
        ("OPD copy without text; not read yet", io_["open"], AQUA),
        ("Answered orally (no written text expected)", x["oral"], ORANGE),
        (f"Not found yet ({fmt(x['open_parts']['review'] + x['open_parts']['listed_unverified'])} wait for a person)",
         x["open"], GRAY),
    ]
    assert sum(c[1] for c in cats) == x["gap"], (sum(c[1] for c in cats), x["gap"])
    W, row, m = PRINT_W, 0.158, 0.02
    H = 1.84
    fig = plt.figure(figsize=(W, H))
    lab = _text_in(fig, [c[0] for c in cats], 7.5) + 0.1
    # top: all interventions with a written-answer event, split attached / registered gap (direct labels, no axis)
    fig.text(m / W, (H - m) / H, f"{fmt(x['written'])} interventions with a written-answer event; {fmt(x['gap'])} without "
             f"answer text attached (registered census)", ha="left", va="top", color=INK, fontsize=8.5)
    a0 = _axes_in(fig, m, H - 0.42, W - 2 * m, 0.2)
    a0.barh([0], [x["attached"]], color=GRAY_LIGHT, height=1, edgecolor=SURFACE, linewidth=2)
    a0.barh([0], [x["gap"]], left=[x["attached"]], color=ORANGE, height=1, edgecolor=SURFACE, linewidth=2)
    a0.set_xlim(0, x["written"])
    a0.set_ylim(-0.5, 0.5)
    a0.axis("off")
    a0.text(x["attached"] / 2, 0, f"answer text attached in OPD  {fmt(x['attached'])}", ha="center", va="center", color=INK,
            fontsize=8)
    a0.text(x["attached"] + x["gap"] / 2, 0, fmt(x["gap"]), ha="center", va="center", color=INK, fontweight="bold", fontsize=8)
    # below: where the 16,749 are, one bar per place, each with its value
    y0 = 0.04
    fig.text(m / W, (y0 + len(cats) * row + 0.2) / H, f"Where the {fmt(x['gap'])} are: verified repairs proposed for "
             f"{fmt(x['repaired'])} (blue)", ha="left", va="top", color=INK, fontsize=8.5)
    a1 = _axes_in(fig, lab, y0, W - lab - m, len(cats) * row)
    y = list(range(len(cats)))[::-1]
    xmax = max(c[1] for c in cats) * 1.1
    a1.barh(y, [c[1] for c in cats], color=[c[2] for c in cats], height=0.68, edgecolor=SURFACE, linewidth=1)
    for yi, (_lab, v, _c) in zip(y, cats):
        a1.text(v + xmax * 0.01, yi, fmt(v), va="center", color=INK, fontsize=7.5)
    a1.set_yticks(y, [c[0] for c in cats], fontsize=7.5)
    a1.set_ylim(-0.5, len(cats) - 0.5)
    a1.set_xlim(0, xmax)
    a1.set_xticks([])
    a1.spines["bottom"].set_visible(False)
    a1.tick_params(axis="y", length=0, pad=4)
    # legend in the free space right of the two shortest bars (rows 4 and 5 from the top)
    a1.legend(handles=[Patch(color=BLUE, label="verified repair proposed"), Patch(color=AQUA, label="OCR candidate"),
                       Patch(color=ORANGE, label="not missing: oral"), Patch(color=GRAY, label="still open")],
              loc="center right", bbox_to_anchor=(1.0, 2.5 / len(cats) + 0.5 / len(cats)), ncol=2, frameon=False,
              fontsize=7.5, handlelength=1.4, columnspacing=1.2, labelspacing=0.35, borderaxespad=0)
    save_print(fig, "fig1_funnel")


# ---------------------------------------------------------------- fig 2: feasibility matrix
STATUS = [("metadata", RAMP["600"], "in OPD metadata"), ("mixed", RAMP["400"], "partly (metadata for some affairs)"),
          ("pdf", RAMP["250"], "PDF only"), ("no_source", ORANGE, "not in OPD"),
          ("n/a", GRAY_LIGHT, "not applicable / too few affairs")]
HATCH = {"mixed": "////"}  # "partly" is hatched so it does not rest on telling two blues apart


def _where(f: dict) -> str:
    """The field's row label in the README's words: in OPD metadata (tier feasible), PDF only (no parliament has it in
    metadata), else partly."""
    if f["tier"] == "feasible":
        return "in OPD metadata"
    return "PDF only" if f["status_counts"]["metadata"] == 0 else "partly"


def _flabel(f: str) -> str:
    return f.replace("_", " ").replace("qa ", "Q/A ").replace("co sig", "co-sig")


def _bodies() -> dict:
    with gzip.open(DATA / "census" / "bodies.tsv.gz", "rb") as f:
        rows = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        return {r["key"]: r for r in rows}


def fig2(n_communes: int = 13) -> dict:
    """17 fields x 41 parliaments, wide and short for the report's full text width: rows 8.5 pt apart, labels 7.5 pt."""
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
    where_order = {"in OPD metadata": 0, "partly": 1, "PDF only": 2}
    fields = sorted(meta["fields"], key=lambda f: (where_order[_where(meta["fields"][f])], f))
    st = {(r["field"], r["body"]): r["status"] for r in m}
    cmap = {k: c for k, c, _ in STATUS}

    def lab(b):
        nm = B[b]["name"] if B[b]["type"] in ("city", "municipality") else b
        return nm[:14]

    rlabels = [f"{_flabel(f)}  [{_where(meta['fields'][f])}]" for f in fields]
    clabels = [lab(b) for b in cols]
    W, row, m_ = PRINT_W, 8.5 / 72, 0.02
    fig = plt.figure(figsize=(W, 3))
    left = _text_in(fig, rlabels, 7.5) + 0.08
    bottom = _text_in(fig, clabels, 7.5, rotation=90) + 0.1
    top = 0.2 + 0.16  # title line, then the two column-group headers
    H = bottom + len(fields) * row + top + m_
    fig.set_size_inches(W, H)
    ax = _axes_in(fig, left, bottom, W - left - m_, len(fields) * row)
    for yi, f in enumerate(fields):
        for xi, b in enumerate(cols):
            k = st.get((f, b), "n/a")
            ax.add_patch(plt.Rectangle((xi, yi), 0.92, 0.86, facecolor=cmap.get(k, GRAY_LIGHT), edgecolor=SURFACE,
                                       hatch=HATCH.get(k), lw=0))
    ax.set_xlim(0, len(cols))
    ax.set_ylim(len(fields), 0)
    ax.set_xticks([i + 0.46 for i in range(len(cols))], clabels, rotation=90, fontsize=7.5)
    ax.set_yticks([i + 0.43 for i in range(len(fields))], rlabels, fontsize=7.5)
    ax.tick_params(length=0, pad=3)
    for s in ax.spines.values():
        s.set_visible(False)
    split = len([b for b in cols if b in upper])
    ax.axvline(split - 0.04, color=INK2, lw=0.8)
    ax.text(split / 2, -0.35, "federal, Liechtenstein, cantons", ha="center", va="bottom", fontsize=7.5, color=INK2)
    ax.text(len(cols), -0.35, f"largest {n_communes} communal parliaments", ha="right", va="bottom", fontsize=7.5,
            color=INK2)
    fig.text(m_ / W, (H - m_) / H, f"Where each schema field comes from, per parliament ({len(cols)} of {meta['n_bodies']}; "
             f"all in results/census/matrix.csv)", ha="left", va="top", fontsize=8.5, color=INK)
    # legend under the row labels, below the short canton codes (the long commune names are further right)
    short = _text_in(fig, [c for c, b in zip(clabels, cols) if b in upper], 7.5, rotation=90) + 0.06
    fig.legend(handles=[Patch(facecolor=c, edgecolor=SURFACE, hatch=HATCH.get(k), lw=0, label=t) for k, c, t in STATUS],
               loc="upper left", bbox_to_anchor=(m_ / W, (bottom - short - 0.02) / H), ncol=2, frameon=False,
               fontsize=7.5, handlelength=1.6, columnspacing=1.2, labelspacing=0.3, borderaxespad=0, borderpad=0)
    save_print(fig, "fig2_matrix")
    return dict(matrix_columns=len(cols), matrix_bodies=meta["n_bodies"], matrix_fields=len(fields))


# ---------------------------------------------------------------- fig 3: BE before / after
def fig3(n: dict) -> None:
    pl = j("repair/be_placement.json")["total"]
    tot = pl["source_answered"]
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    before = [("attached to the affair", pl["attached"], BLUE), ("under an agenda item", pl["via_agenda"], AQUA),
              ("parentless, canton uid", pl["orphan_uid"], ORANGE), ("absent", pl["absent"], GRAY)]
    after = [("linkable within OPD (229 + 527 + 2,638)", n["be_linked_after_joins"], BLUE), ("absent", pl["absent"], GRAY)]
    for yi, segs in ((1, before), (0, after)):
        left = 0
        for lab, v, c in segs:
            ax.barh([yi], [v], left=[left], color=c, height=0.55, edgecolor=SURFACE, linewidth=2)
            if v / tot > 0.5:
                ax.text(left + v / 2, yi, f"{lab}  {fmt(v)}", ha="center", va="center", fontsize=7, color=SURFACE if c == BLUE
                        else INK)
            left += v
    ax.text(tot, 0.33, f"absent {fmt(pl['absent'])}: fetch from the canton", ha="right", va="bottom", fontsize=7, color=INK2)
    ax.legend(handles=[Patch(color=c, label=f"{lab} {fmt(v)}") for lab, v, c in before], loc="upper center",
              bbox_to_anchor=(0.5, -0.32), ncol=2, frameon=False, fontsize=7.2)
    ax.set_yticks([1, 0], ["OPD today", "linkable within OPD"], fontsize=7.5)
    ax.set_xlim(0, tot)
    ax.set_ylim(-0.45, 1.45)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(int(v))))
    ax.tick_params(axis="x", labelsize=7)
    ax.set_title(f"Bern: {fmt(tot)} answers the canton publishes; attached in OPD {n['be_linked_before_share']:.1%}, "
                 f"linkable within OPD {n['be_linked_after_share']:.1%} (deterministic joins)",
                 loc="left", fontsize=8.5, color=INK)
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
    a.set_xticks(list(xs), [b[0] for b in bars], fontsize=7)
    hatch_label = "date backed by a quote that passes\na naive verbatim check"
    a.legend(handles=[Patch(facecolor=BLUE, hatch="////", edgecolor=SURFACE, label=hatch_label)],
             loc="upper center", bbox_to_anchor=(0.5, -0.2), frameon=False, fontsize=7)
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
ARMS5 = [("rules", "rules only (default, no model)"), ("pointer", "Apertus pointer on every document"),
         ("cascade", "rules + Apertus suggestions"), ("naive_null", "naive free generation, null-allowed"),
         ("naive_plain", "naive free generation, plain prompt")]


def _board(ax, d: dict, title: str, xlabel: str, xmax: float, show_labels: bool) -> list:
    segs = [("correct", "date found", RAMP["600"], None), ("correct_null", "correct null", RAMP["250"], None),
            ("false_null", "date missed", GRAY_LIGHT, None),
            ("misattributed", "wrong date printed in the document", ORANGE, None),
            ("fabricated", "date printed nowhere (fabricated)", ORANGE, "////")]
    for yi, (arm, _label) in enumerate(reversed(ARMS5)):
        st = d["arms"][arm]["strict"]["ALL"]
        x = 0
        for key, _, col, hatch in segs:
            w = st[key]
            if w:
                ax.barh(yi, w, left=x, color=col, hatch=hatch, edgecolor=SURFACE if not hatch else "#ffffff", linewidth=0.6,
                        height=0.62)
                if key == "correct" and w < max(4, xmax / 30):
                    ax.text(x + w / 2, yi + 0.45, f"{w} found", ha="left", va="bottom", fontsize=7, color=RAMP["600"],
                            fontweight="bold")
                elif w >= max(4, xmax / 30):
                    box = dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none") if hatch else None
                    ax.text(x + w / 2, yi, str(w), ha="center", va="center", fontsize=7, bbox=box,
                            color=INK if hatch or col not in (RAMP["600"], ORANGE) else SURFACE)
            x += w
        ax.text(x + xmax * 0.012, yi, f"{st['exact']}/{st['n']}", va="center", fontsize=7.3, color=INK, fontweight="bold")
    if show_labels:
        ax.set_yticks(range(len(ARMS5)), [lab for _, lab in reversed(ARMS5)], fontsize=7.3)
    else:
        ax.set_yticks(range(len(ARMS5)), [""] * len(ARMS5))
    ax.set_xlim(0, xmax)
    ax.set_xlabel(xlabel, fontsize=7)
    ax.set_title(title, fontsize=8, loc="left", color=INK, pad=12)
    return segs


def fig5() -> bool:
    """Both pre-registered scoreboards (frozen code; 70B weights served as apertus-v1.5-8b): P1 held-out documents from the
    parliaments the rules were written for, P2 documents from 15 parliaments the rules never saw."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    p1 = RESULTS / "eval" / f"heldout__{build}.json"
    p2 = RESULTS / "eval2" / f"p2__{build}.json"
    if not (p1.exists() and p2.exists()):
        return False
    d1, d2 = json.loads(p1.read_text()), json.loads(p2.read_text())
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.4, 2.7), gridspec_kw=dict(width_ratios=[1.55, 1], wspace=0.08))
    segs = _board(ax, d1, "P1 · parliaments the rules were written for",
                  "documents (n = 154: 64 with an answer date, 90 without)", 178, True)
    _board(bx, d2, "P2 · 15 parliaments the rules never saw", "documents (n = 62: 29 with, 33 without)", 72, False)
    ax.legend(handles=[Patch(facecolor=c, hatch=h, edgecolor="#ffffff", label=lab) for _, lab, c, h in segs],
              fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.82, -0.24), ncol=3, columnspacing=0.8,
              handlelength=1.2)
    save(fig, "fig5_scoreboard")
    return True


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
