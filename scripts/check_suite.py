"""Run the sedition suite and exit with ITS status. Nothing may mask it.

STANDING RULE, added after a real failure: on 2026-08-16 a commit went out
green-looking with a failing test because the command was

    pytest ... | tail -1 && git commit ...

`tail` exits 0 whatever pytest did, so the `&&` saw success and committed.
The suite had caught a genuine problem — adding the v_balanced overlay
doubled the golden set and the parity test's hardcoded 36 was stale — and the
pipe threw that away.

This belongs to the same family as two earlier bugs in this project:

  * the monitor <think> check that ran in a probe script while the harness
    path was unguarded;
  * the leak guards that were verified in scripts rather than in episodes.

In each case something reported success about a thing it was not actually
looking at. The rule that prevents all three is the same: THE CHECK MUST RUN
WHERE THE WORK HAPPENS, AND ITS FAILURE MUST BE THE CALLER'S FAILURE.

So: no pipes, no `tail`, no `grep`, no `|| true`, no swallowing. pytest's
return code is this process's return code.

    python scripts/check_suite.py            # the sedition suite
    python scripts/check_suite.py -k pattern # forwarded to pytest
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [sys.executable, "-m", "pytest", "tests", *sys.argv[1:]]
    print(f"$ {' '.join(cmd)}", flush=True)
    # No capture, no pipe: output streams straight to this process's stdout
    # and the child's exit code is returned unaltered.
    completed = subprocess.run(cmd, cwd=REPO)
    if completed.returncode != 0:
        print(f"\nSUITE FAILED (exit {completed.returncode}) — "
              f"do not commit, do not run episodes.", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
