# Incidents

Operational incidents of Gegenprobe: what happened, what was affected, what was done. Newest first.

## 2026-10-10: three files fetched from a path www4.ti.ch's robots.txt disallows

**What happened.** `gegenprobe.net.allowed()` checked robots.txt with Python's `urllib.robotparser`. That parser applies
the **first** rule of a group whose path is a prefix of the URL. RFC 9309 §2.2.2 requires the **most specific (longest)**
matching rule, with an allow winning a tie. The two disagree when a group lists a broad rule before a narrow one, and
www4.ti.ch does exactly that:

    User-agent: *
    Allow: /
    Disallow: /poteri/gc/ricerca-messaggi-e-atti/ricerca/
    Disallow: /user_librerie/php/GC/allegato.php

For `/user_librerie/php/GC/allegato.php?allid=…`, urllib stops at `Allow: /` and allows the URL. RFC 9309 picks
`Disallow: /user_librerie/php/GC/allegato.php` (34 octets against 1) and disallows it.

**When.** 10 Oct 2026, during the source-adapter run (upgrade U1, `docs/adapters.md`), while building the Ticino route.

**What was fetched.** Three Ticino answer files:
`https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=115005`, `…?allid=119023` and `…?allid=137701`. The audit
in step 5 finds no other fetched URL on a disallowed path.

**What was done.**

1. The three files and everything derived from them (PDF and text caches, URL cache entries) were deleted from WORK.
   No committed result uses them: Ticino's 729 verified rows and all its review rows read OPD's own copies on
   files.openparldata.ch (`results/repair/adapters/TI.json`), and no committed file contains the three URLs outside the
   documentation.
2. The adapters got their own RFC 9309 check (`repair/adapters/robots.py`) in front of every request, from commit
   `6a3ba3c` (11 Oct 2026). The Ticino Word/PDF route stays off: the answer files are disallowed.
3. 11 Oct 2026: the fix now covers **every entry point**, not only the adapters. `src/gegenprobe/robots9309.py` is the
   single matcher (longest match, allow wins ties, `*` and a final `$`, empty `Disallow` allows, groups for our product
   token merged). `src/sitecustomize.py` installs it into `urllib.robotparser.RobotFileParser` at interpreter start;
   Python's `site` module imports `sitecustomize` from the first `sys.path` entry that has one, and every entry point
   puts `src/` on `PYTHONPATH`:

   | entry point | how `src/` gets on sys.path |
   |---|---|
   | `make test`, `make claims`, every host `make` target | Makefile `export PYTHONPATH := src:.` |
   | `make run` (Docker), Docker nightly unit, CI `nightly-smoke` | Dockerfile `ENV PYTHONPATH=/app/src:/app` (the units run the image) |
   | venv nightly unit | `Environment=PYTHONPATH=/opt/gegenprobe/track_2a/src` (absolute, independent of `WorkingDirectory=/var/lib/gegenprobe`) |
   | subprocesses of the nightly job and its smoke test | `monitor/nightly.py` and `monitor/smoke.py` set `PYTHONPATH` to `<checkout>/src` |
   | CLI (`python -m gegenprobe …`, `docs/convert-your-own.md`) | `export PYTHONPATH=src:.` |
   | CI `test` job | `PYTHONPATH=src:. python -m pytest` |
   | bare `pytest` (pyproject adds `src` only after start-up) | `tests/conftest.py` installs the same patch |

   `gegenprobe/net.py` is locked (LOCK2) and was not edited: it still calls `RobotFileParser.parse()` and
   `.can_fetch()`, which now follow RFC 9309. Importing `repair/adapters/robots.py` installs the patch as well.
4. Tests: `tests/test_robots9309.py` (the ti.ch case, `*` and `$`, ties, empty `Disallow`, percent escapes, group
   selection; `net.allowed()`/`net.get()` refuse the three allegato.php URLs with a stubbed robots.txt and no network;
   sitecustomize loads under the `PYTHONPATH` of the Makefile, the Dockerfile, the venv unit and the nightly
   subprocesses). CI (`.github/workflows/ci.yml`) asserts the patch on the runner (job `test`) and inside the built
   image (job `nightly-smoke`).
5. Audit (`python -m gegenprobe.repair.adapters.robots_audit`, robots.txt read 11 Oct 2026,
   `results/repair/adapters/robots_audit.json`): of the 7,463 documents the adapters fetched, the 7,393 on hosts whose
   robots.txt could be read include no disallowed path; the 11 API and index request types are allowed. 70 documents
   (www.ilef.ch 52, www.pratteln.ch 18) could not be re-checked because both hosts are unreachable from our network
   today; `net` fetched them only while their robots.txt was readable (it fails closed otherwise). The other disallowed
   URLs in the audit (1,157: Ticino 801, Locarno 259, Kriens 73, Arbon 24) are parliament URLs that OPD records next to
   its own copy or text; the adapters read OPD's copy or text instead and did not request them.

**Lesson.** A standard-library parser does not necessarily implement the standard. The network layer now has one
robots.txt implementation, tested on the RFC's matching rules and on the site that exposed the difference.
