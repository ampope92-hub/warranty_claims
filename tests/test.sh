#!/bin/bash

# Verifier entrypoint. Runs in the verifier container, not the agent's — it sees only the paths
# declared in `artifacts`. All tooling is baked into tests/Dockerfile; nothing is fetched here.

set -uo pipefail

mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt

# Fold stderr into stdout. Only stdout survives into the feedback bundle, so a script that
# dies on stderr dies invisibly -- which is what made the process-group self-kill above take
# three rounds to find.
exec 2>&1

# This shell's own process group. Each run below is started under `setsid` so it gets a group
# of its own that can be torn down as a unit, but /proc can be read in the window before
# setsid(2) has taken effect, and in that window it still reports THIS group. Killing that
# group kills the verifier itself: the log stops mid-script, pytest never runs, no ctrf.json
# is written and the reward stays 0. Three rounds were lost to exactly that before the cause
# was found, so no group is ever signalled unless it is demonstrably not our own.

# The graded numbers must come out of the agent's own program, so it is recompiled from the
# collected sources and run here. That executes code the agent wrote, so it runs as the
# unprivileged `runner`. Artifacts land owned by root, so hand the project over first and pin the
# shipped exports read-only. /logs is left alone — Harbor owns it and the reward is written there
# last, after every agent process is dead.
chown -R runner:runner /app/model /app/out
chmod -R a-w /app/data

as_runner() {
  setpriv --clear-groups --no-new-privs --reuid runner --regid runner "$@"
}

# The shipped tests/ directory lands here at runtime, so the verifier's own code and a plaintext
# copy of the answer key sit under /tests just as agent-authored code is about to run. Close the
# whole directory to the build user first: root still reads it, `runner` cannot traverse it. If it
# is still reachable the run is abandoned with reward 0 rather than graded. The graded costs are
# read from the root-only copy at /opt/golden either way.
chmod 700 /tests 2>/dev/null || true
if as_runner bash -c 'test -r /tests/test_outputs.py || test -r /tests/golden/batch_truth.dat' 2>/dev/null; then
  echo "FATAL: /tests is still reachable by the unprivileged build user; the verifier's code and"
  echo "answer key are exposed to agent-authored code, so this run cannot be graded."
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi
echo "verifier files closed to the unprivileged build user"

# run_once <output-path> — recompile and run the agent's project, capturing its output.
#
# Each run happens in its own session so every process it spawns shares one process group that
# can be torn down as a unit: a double-forked child left alive would still be around during
# grading, where it could rewrite the captured output or the reward. The result is moved to a
# root-owned path and pytest reads that — running the agent's binary from inside pytest would
# execute agent code as root in the container that decides the reward. stderr is deliberately not
# redirected: it flows to this log, where a compile failure is readable.
run_once() {
  local out="$1" pid pgid
  rm -f /app/out/predictions.dat
  setsid \
    setpriv --clear-groups --no-new-privs --reuid runner --regid runner \
    bash /app/model/build.sh &
  pid=$!
  wait "$pid"
  echo "build.sh exit status: $?"
  # `setsid` makes the launched process a session leader, and a session leader's process group
  # id is its own pid, so the group is addressed directly as -"$PID". The previous version read
  # the group id back out of /proc instead, which races setsid(2): in the window before it takes
  # effect /proc still reports the child in THIS shell's group, and the kill then took down the
  # verifier itself -- silently, with no pytest output and the reward left at 0.
  kill -TERM -- -"$pid" 2>/dev/null || true
  kill -KILL -- -"$pid" 2>/dev/null || true
  as_runner bash -c 'kill -9 -1' 2>/dev/null || true
  # Only a regular file is ever staged. The build runs as `runner` and cannot read the answer
  # key, but it can drop a symlink at this path pointing into /opt/golden or /opt/holdout: a
  # plain mv preserves the link, and pytest -- running as root, which those modes do not stop --
  # would then read the verifier's own truth back as the agent's quotes and score a perfect fit.
  # Anything that is not a regular file is discarded, so the run counts as having written nothing.
  if [ -L /app/out/predictions.dat ] || [ ! -f /app/out/predictions.dat ]; then
    echo "no regular predictions.dat was produced (absent, or not a regular file)"
    rm -f /app/out/predictions.dat
  else
    mv /app/out/predictions.dat "$out" 2>/dev/null || true
    chown root:root "$out" 2>/dev/null || true
    chmod 600 "$out" 2>/dev/null || true
  fi
}

# The task states the model lives in C and that the box carries nothing past the C standard
# library. This image ships a Python interpreter because pytest scores the result with it, and
# the verifier re-runs the agent's own build.sh in here -- so a build.sh that shelled out to
# Python would have the graded costs come from something other than the C project, and pass.
# The interpreter is closed to the build user for the duration of the runs; root still executes
# it afterwards to score them.
python_bins=""
for py in /usr/local/bin/python /usr/local/bin/python3 /usr/local/bin/python3.13 \
          /usr/bin/python /usr/bin/python3; do
  [ -e "$py" ] && python_bins="$python_bins $py"
done
lock_python()   { for py in $python_bins; do chmod 700 "$py" 2>/dev/null || true; done; }
unlock_python() { for py in $python_bins; do chmod 755 "$py" 2>/dev/null || true; done; }
lock_python

# The shipped batch.
run_once /opt/run_batch.dat

# Then a batch the agent has never seen. Everything above grades the export that ships inside
# the agent's image, so a program could fit once and write the resulting costs into the C
# source. The holdout is baked into this image and never present in any container the agent can
# reach. The agent's own export is put back byte-for-byte afterwards, so the sha256 check still
# tests exactly what the agent left.
cp -a /app/data /opt/agent_data
install -o root -g root -m 0444 /opt/holdout/history.dat /app/data/history.dat
install -o root -g root -m 0444 /opt/holdout/batch.dat    /app/data/batch.dat
run_once /opt/run_holdout.dat
rm -f /app/data/history.dat /app/data/batch.dat
cp -a /opt/agent_data/. /app/data/
chmod -R a-w /app/data

unlock_python

# Nothing the agent started may be alive while pytest runs or while the reward is written.
as_runner bash -c 'kill -9 -1' 2>/dev/null || true

# -P keeps the working directory (/app) off sys.path. The program runs as `runner` and writes
# into /app, so without this it could drop an /app/pytest.py holding sys.exit(0); `python -m
# pytest` would import that no-op, exit 0, and bypass the whole suite for reward 1.
python -P -m pytest -o cache_dir=/tmp/pytest_cache \
  --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
exit_code=$?
if [ "$exit_code" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

# Harbor grades from reward.txt, never from this script's exit status.
exit 0
