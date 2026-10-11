# Deviations from PREREG8 (P7)

## D1: Qwen check started through a shim for the gateway path (no effect on any registered result)
`eval/p7/qwen8.py` (hashed in LOCK8) reads the gateway directory from `audit3.GATEWAY`. Commit f540e91 (Ops: development
paths from `GP_GATEWAY_DIR`, `gegenprobe/devpaths.py`) removed that attribute from `audit3.py` before LOCK8 was written,
so LOCK8 hashed the new `audit3.py` and a `qwen8.py` that no longer runs. The locked file was not edited. The check was
run with the attribute set back from `devpaths.gateway_dir()` (the same directory, `~/Desktop/hackapertus/gateway`) before
`qwen8.main()` was called:

    PYTHONPATH=src:. python -c "from gegenprobe import devpaths; from gegenprobe.repair.adapters import audit3; \
        audit3.GATEWAY = devpaths.gateway_dir(); from eval.p7 import qwen8; qwen8.main()"

Model, prompt, tag (`2a-p7-qwen`), cap, served-model check and output path are as locked. The Qwen check changes no gold
label and no decision; H1–H4 do not read it.
