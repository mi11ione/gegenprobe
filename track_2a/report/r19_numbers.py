"""Display-ready numbers for the round-19 docs pass, derived only from committed files, so claims.tsv can trace them.

  * P11 (EXPLORATORY, eval/p11/PROTOCOL.md, LOCKP11): the Italian cell (IT: answer date and author roles per arm, with
    Wilson 95% intervals as printed, the in-sample flags per body, the documents read from OPD's copy, annotator
    agreement) and the cell outside interventions (NI: the converter's valid v0.2 records, the 17 fields grouped by the
    gold verdicts, the new roles the annotators needed, annotator agreement), from results/p11/*_tables.json,
    *_agreement.json, it_arms_pointer.json, ni_arms_offline.json and sample.json;
  * the gateway build (P11 D1, eval/p11/DEVIATIONS_P11.md): every committed gateway response in
    data/model_cache/publicai_swiss-ai_apertus-v1.5-8b/ (the cache `make run` replays) by served label and
    system_fingerprint, the last one's time, and the probe of 12 Oct 2026 (results/p11/served_model_probe.json).

Field groups (NI): a field "carries over" when every gold verdict is fits or not_printed; it "does not apply" when
not_applicable is the verdict of a majority of the 15 affairs; it "needs new roles" when at least one gold verdict is
new_role. The three groups are disjoint on the committed gold and cover the 17 fields (checked below).

No network, no model.

    PYTHONPATH=src:. python -m report.r19_numbers   -> results/report/r19_numbers.json
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter

from gegenprobe.paths import RESULTS, ROOT

OUT = RESULTS / "report" / "r19_numbers.json"
P11 = RESULTS / "p11"
CACHE = ROOT / "data" / "model_cache" / "publicai_swiss-ai_apertus-v1.5-8b"
BODY = {"TI": "Ticino", "5254": "Mendrisio", "5192": "Lugano", "5113": "Locarno", "5002": "Bellinzona"}


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _pct_ci(ci) -> str:
    f = lambda v: "100" if round(100 * v, 1) == 100 else f"{100 * v:.1f}"  # noqa: E731
    return f"[{f(ci[0])}, {f(ci[1])}]"


def it_cell() -> dict:
    t = _j(P11 / "p11_it_tables.json")
    ag = _j(P11 / "p11_it_agreement.json")
    ptr = _j(P11 / "it_arms_pointer.json")
    arms = {}
    for k, name in (("pointer", "pointer"), ("rules", "rules"), ("latest_on_answer_document", "latest"),
                    ("converter_record", "record")):
        a = t["answer_date"]["arms"][k]["strict"]["ALL"]
        arms[name] = dict(exact=a["exact"], n=a["n"], printed_right=a["correct"], null_right=a["correct_null"],
                          false_null=a["false_null"], invented=a["invented"], invented_on_null=a["invented_on_null"],
                          ci=_pct_ci(a["exact_ci"]))
    ar = t["author_roles"]["arms"]["ALL"]
    def _p(x: float) -> str:  # two decimals, or three where that is exact (7/8 = 0.875)
        return f"{x:.3f}" if abs(round(x, 3) - x) < 1e-12 and f"{x:.3f}"[-1] != "0" else f"{x:.2f}"
    roles = {k: dict(matched=v["matched"], printed=v["pairs_predicted"], gold=v["pairs_gold"], affairs=v["affairs"],
                     precision=_p(v["precision"]), recall=f"{v['recall']:.2f}", f1=f"{v['f1']:.2f}")
             for k, v in ar.items()}
    ins = t["in_sample_for"]
    in_sample = {flag: [BODY[b] for b in BODY if ins[b][flag]] for flag in ("date_rules", "role_rules",
                                                                          "role_reader_development")}
    reader_bodies = Counter(BODY[a["stratum"]] for a in ptr["per_affair"] if a.get("role_reader"))
    fields = ag["fields"]
    return dict(
        n=t["n"], bodies=len(t["by_stratum"]), by_body={BODY[k]: v for k, v in t["by_stratum"].items()},
        documents=sum(t["documents_by_route"].values()), documents_opd_copy=t["documents_by_route"]["opd_copy"],
        gold_printed=t["answer_date"]["gold"]["gold:printed"], gold_null=t["answer_date"]["gold"]["gold:null"],
        answer_date=arms, roles=roles, in_sample=in_sample,
        in_sample_n={k: len(v) for k, v in in_sample.items()},
        reader_affairs=ptr["n_role_reader"], reader_by_body=dict(reader_bodies),
        reader_stopped_at_affair=ptr["n_role_reader"] + 1, date_pointer_affairs=ptr["n_date_pointer"],
        cached_replays_frozen=sum(ptr["deviation"]["replayed_from_cache_by_label_and_fingerprint"].values()),
        agreement=dict(answer_date=f"{fields['answer_date']['raw']}/{fields['answer_date']['n']}",
                       people=f"{fields['people']['raw']}/{fields['people']['n']}",
                       people_pair_f1=ag["people_pair_f1_A1_vs_A2"],
                       type=f"{fields['type']['raw']}/{fields['type']['n']}", type_kappa=fields["type"]["kappa"],
                       language=f"{fields['language']['raw']}/{fields['language']['n']}",
                       fields_to_a3=ag["disputed_fields"]),
        frame_answer_doc_not_answer=t["stop_rules"]["frame_check"]["answer_doc_not_executive_answer"],
    )


def ni_cell() -> dict:
    t = _j(P11 / "p11_ni_tables.json")
    ag = _j(P11 / "p11_ni_agreement.json")
    off = _j(P11 / "ni_arms_offline.json")
    n = t["n"]
    carry, napp, new = [], [], []
    for f, v in t["fields"].items():
        verd = v["by_type"]["ALL"]["verdicts"]
        if verd.get("new_role"):
            new.append((f, verd["new_role"]))
        elif verd.get("not_applicable", 0) * 2 > n:
            napp.append((f, verd["not_applicable"]))
        elif set(verd) <= {"fits", "not_printed"}:
            carry.append(f)
        else:
            raise ValueError(f"field {f} fits no group: {verd}")
    assert len(carry) + len(napp) + len(new) == len(t["fields"]) == 17
    new_by_type: dict[str, set] = {"GA": set(), "PI": set()}
    for items in t["new_roles"].values():
        for it in items:
            new_by_type[it["stratum"].split(":")[0]].add(it["id"])
    types = Counter(s.split(":")[0] for s in t["by_stratum"] for _ in range(t["by_stratum"][s]))
    st = t["converter"]["status"]["ALL"]
    valid = t["converter"]["valid_v0_2_records"]
    ok = [a for a in off["per_affair"] if a["converter_status"] == "ok"]
    by_rec = t["converter"]["gold_verdict_by_record_status"]
    raw = sum(v["raw"] for v in ag["fields"].values())
    cells = sum(v["n"] for v in ag["fields"].values())
    return dict(
        n=n, government_business=types["GA"], parliamentary_initiatives=types["PI"],
        bodies=len({a["body"] for a in off["per_affair"]}),
        kind_conforms=f"{t['affair_kind_conforms_to_opd_type']['k']}/{t['affair_kind_conforms_to_opd_type']['n']}",
        valid_records=f"{valid['k']}/{valid['n']}", valid_k=valid["k"], valid_ci=_pct_ci(valid["wilson95"]),
        no_documents=st.get("no_documents", 0), valid_bodies=sorted({a["body"] for a in ok}),
        valid_answer_date_not_applicable=by_rec["date_answer"].get("not_applicable|value", 0),
        fields=dict(n=len(t["fields"]), carry_over=len(carry), not_applicable=len(napp), new_roles=len(new),
                    carry_over_fields=carry, not_applicable_fields=dict(napp), new_role_fields=dict(new)),
        new_role_affairs=dict(GA=len(new_by_type["GA"]), PI=len(new_by_type["PI"])),
        agreement=dict(raw=f"{raw}/{cells}", fields_to_a3=ag["disputed_fields"],
                       packets_with_a3=ag["disputed_packets"],
                       lowest_kappa={k: ag["fields"][k]["kappa"] for k in
                                     ("decision_outcome", "date_dispatch", "government_recommendation")}),
    )


def gateway_build() -> dict:
    labels, fps, ts = Counter(), Counter(), []
    for p in sorted(CACHE.rglob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        r = d.get("resp") or {}
        labels[r.get("model")] += 1
        fps[r.get("system_fingerprint")] += 1
        if d.get("ts"):
            ts.append(int(d["ts"]))
    last = dt.datetime.fromtimestamp(max(ts), dt.timezone.utc)
    pr = _j(P11 / "served_model_probe.json")
    calls = pr["calls"]
    return dict(
        committed_responses=sum(labels.values()), labels=dict(labels), fingerprints=dict(fps),
        n_labels=len(labels), n_fingerprints=len(fps),
        last_response_utc=last.strftime("%Y-%m-%dT%H:%M:%SZ"), last_response_hhmm=last.strftime("%H:%M"),
        probe=dict(replays=len(calls), labels_live=pr["labels_served_live"], fingerprints_live=pr["fingerprints_live"],
                   frozen_fingerprint=pr["frozen_build_fingerprint"],
                   relabelled=sum(1 for c in calls if c["live"]["model"] != c["cached"]["model"]),
                   other_fingerprint=sum(1 for c in calls
                                         if c["live"]["system_fingerprint"] != c["cached"]["system_fingerprint"]),
                   max_abs_logprob_delta=round(pr["max_abs_logprob_delta"], 2),
                   greedy_changed=sum(1 for c in calls if c.get("greedy_equal") is False),
                   role_reader_requests=sum(1 for c in calls if c["kind"] == "next_top"),
                   usd=pr["usd"]),
    )


def main() -> int:
    it, ni = it_cell(), ni_cell()
    out = dict(label="display numbers from committed files (report/r19_numbers.py); P11 is EXPLORATORY",
               p11=dict(it=it, ni=ni), gateway=gateway_build())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
