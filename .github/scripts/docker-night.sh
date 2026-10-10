#!/bin/sh
# One night of the installed gegenprobe-nightly.service under systemd, with its outputs collected into
# $GITHUB_WORKSPACE/nights/night<N>/ (used by .github/workflows/nightly-real-docker.yml; N = 1 or 2).
# The state under /var/lib/gegenprobe is left in place, so night N+1 runs against night N.
set -u
n="$1"
d="$GITHUB_WORKSPACE/nights/night$n"
mkdir -p "$d"
state=/var/lib/gegenprobe/work/nightly/state.json
if sudo test -f "$state"; then state_before=true; else state_before=false; fi
nproc; free -m; df -h /var/lib
t0=$(date -u +%s); started=$(date -u +%FT%TZ)
rc=0; sudo systemctl start gegenprobe-nightly.service || rc=$?   # non-zero when the night exits 1, 2 or 3
t1=$(date -u +%s); ended=$(date -u +%FT%TZ)
systemctl show gegenprobe-nightly.service -p Result -p ExecMainStatus -p ExecMainStartTimestamp \
  -p ExecMainExitTimestamp -p CPUUsageNSec -p IOReadBytes -p IOWriteBytes | tee "$d/systemctl_show.txt"
status=$(systemctl show gegenprobe-nightly.service -p ExecMainStatus --value)
result=$(systemctl show gegenprobe-nightly.service -p Result --value)
gen=$(sudo python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["index"]["generated_at"])' "$state" 2>/dev/null || echo "")
printf '{"night": %s, "started": "%s", "ended": "%s", "wall_s": %d, "systemctl_start_rc": %d, "result": "%s", "exit_status": "%s", "state_before": %s, "index_generated_at": "%s", "variant": "docker (install.sh, gegenprobe:0.1.0)", "user_agent": "%s", "runner": "%s, %s vCPU"}\n' \
  "$n" "$started" "$ended" $((t1 - t0)) "$rc" "$result" "$status" "$state_before" "$gen" "$UA" "${ImageOS:-ubuntu}" "$(nproc)" \
  | tee "$d/night.json"
sudo cp -r /var/lib/gegenprobe/results "$d/results" || true
sudo du -sh /var/lib/gegenprobe/work /var/lib/gegenprobe/work/* > "$d/work_du.txt" 2>&1 || true
sudo journalctl -u gegenprobe-nightly.service -u gegenprobe-nightly-failure.service --since "$started" --no-pager \
  -o short-iso > "$d/journal.txt" || true
{ head -n 60 "$d/journal.txt"; echo "[...]"; tail -n 120 "$d/journal.txt"; } > "$d/journal_excerpt.txt"
sudo chown -R "$(id -u):$(id -g)" "$d"
cat "$d/results/run.json" || true
echo "night $n: wall time $((t1 - t0)) s; result $result; exit status $status"
exit 0
