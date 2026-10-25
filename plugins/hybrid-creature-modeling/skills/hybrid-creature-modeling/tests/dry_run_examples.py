"""Integration test: headless dry run of every example creature, then clean up its output.

  python tests/dry_run_examples.py [--blender <path to blender>] [--keep] [--only dragon komodo ...]

Each example runs with CREATURE_DRY_RUN=1 into its own folder under the system temp directory; the test checks the
exit code, that the log has no errors, and that the v1.3 surface plan was resolved and mapped to body-field regions.
Folders are deleted afterwards unless --keep (dragon dry runs write about 0.4 GB each).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
EXAMPLES = ("dragon", "komodo", "raptor")

ap = argparse.ArgumentParser()
ap.add_argument("--blender", default=os.environ.get("BLENDER", "blender"))
ap.add_argument("--keep", action="store_true")
ap.add_argument("--only", nargs="*", default=None)
args = ap.parse_args()

failed = 0
for name in args.only or EXAMPLES:
    out = tempfile.mkdtemp(prefix=f"{name}_dry_test_")
    env = dict(os.environ, CREATURE_DRY_RUN="1", CREATURE_DRY_DIR=out)
    env.pop("CREATURE_KIT_DIR", None)          # the example must find the skill's own scripts/
    script = os.path.join(SKILL, "examples", name, f"{name}.py")
    p = subprocess.run([args.blender, "-b", "--factory-startup", "--python", script], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    problems = []
    log_path = os.path.join(out, f"{name}_log.json")
    if p.returncode != 0:
        problems.append(f"exit code {p.returncode}")
    if not os.path.isfile(log_path):
        problems.append("no log written")
    else:
        log = json.load(open(log_path, encoding="utf-8"))
        if log.get("errors"):
            problems.append(f"{len(log['errors'])} error(s): {log['errors'][0][-300:]}")
        if not log.get("surface_plan"):
            problems.append("surface plan not in the log")
        if not log.get("surface_region_vertices"):
            problems.append("surface regions not mapped to body fields")
        skipped = (log.get("anatomy") or {}).get("skipped")
        info = f"anatomy skipped {skipped}, regions {len(log.get('surface_plan') or [])}"
    print(f"[dry] {'PASS' if not problems else 'FAIL'} {name}: " + ("; ".join(problems) if problems else info))
    failed += bool(problems)
    if args.keep:
        print(f"[dry]   kept {out}")
    else:
        shutil.rmtree(out, ignore_errors=True)
print(f"[dry] {len(args.only or EXAMPLES) - failed}/{len(args.only or EXAMPLES)} passed")
sys.exit(1 if failed else 0)
