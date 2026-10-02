#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installation smoke test for dsh-origin-thesis.

Verifies that this checkout/deployment is actually wired up correctly, without
touching Origin and without needing a DSH session. Run it after cloning, after
`sync_to_vendor.ps1`, or whenever the tools do not show up in DSH.

  python tests/smoke.py                     # everything, incl. MCP handshake
  python tests/smoke.py --skip-handshake    # no subprocess / stdio check
  python tests/smoke.py --python C:/path/to/python.exe

Checks, in order:

  1. the launcher exists and the server file sits next to it
  2. the chosen interpreter can `import originpro`
  3. `--info` reports a self-consistent map (scripts present, profiles load)
  4. `--list-tools` registers the expected tool set
  5. a real MCP stdio handshake: initialize -> tools/list -> tools/call
     (`thesis_batch_dir_info`), i.e. exactly what DSH does at startup

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # repository / package root

EXPECTED_TOOLS = {
    "thesis_apply_style_only", "thesis_batch", "thesis_batch_dir_info",
    "thesis_export_open", "thesis_export_project", "thesis_format_composite",
    "thesis_format_graph", "thesis_format_project", "thesis_style_set",
    "thesis_style_show", "thesis_styles_list", "thesis_verify_project",
}
EXPECTED_PROFILES = {"thesis", "composite", "manuscript"}
EXPECTED_SCRIPTS = {"format_thesis_figures", "format_composite", "export_figures"}

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("  %s %-44s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def launcher_invocation(launcher, extra):
    """How to invoke the launcher: .cmd needs cmd /c, .sh needs sh."""
    if launcher.lower().endswith(".cmd") or launcher.lower().endswith(".bat"):
        return ["cmd.exe", "/c", launcher] + list(extra)
    return [launcher] + list(extra)


def find_launcher() -> str:
    for name in ("start-thesis-mcp.cmd", "start-thesis-mcp.sh"):
        p = os.path.join(ROOT, name)
        if os.path.isfile(p):
            return p
    return ""


def handshake(py, server, timeout=120):
    """Speak MCP over stdio exactly like DSH does. Returns (ok, detail)."""
    proc = subprocess.Popen([py, "-u", "-X", "utf8", server],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def send(msg):
        proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def recv(t):
        end = time.time() + t
        while time.time() < end:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        raise TimeoutError("no reply within %ss" % t)

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "smoke", "version": "1"}}})
        init = recv(timeout)
        name = (init.get("result") or {}).get("serverInfo", {}).get("name")
        send({"jsonrpc": "2.0", "method": "notifications/initialized",
              "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = recv(timeout)
        got = {t["name"] for t in (tools.get("result") or {}).get("tools", [])}
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "thesis_batch_dir_info", "arguments": {}}})
        call = recv(timeout)
        txt = "".join(c.get("text", "")
                      for c in (call.get("result") or {}).get("content", []))
        info = json.loads(txt)
        return (got == EXPECTED_TOOLS and name == "origin_thesis" and info.get("ok"),
                "serverInfo=%s, tools=%d, batch_dir_info.ok=%s"
                % (name, len(got), info.get("ok")))
    except Exception as exc:                      # noqa: BLE001 - report anything
        return False, "handshake failed: %s" % exc
    finally:
        try:
            proc.stdin.close()
            proc.terminate()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter that should drive Origin "
                         "(default: the one running this script)")
    ap.add_argument("--skip-handshake", action="store_true",
                    help="skip the MCP stdio handshake (no subprocess spawned)")
    args = ap.parse_args()

    print("dsh-origin-thesis smoke test")
    print("  root     : %s" % ROOT)
    print("  python   : %s" % args.python)
    print("")

    print("[1] files")
    launcher = find_launcher()
    check("launcher present", bool(launcher),
          launcher or "expected start-thesis-mcp.cmd next to this package")
    server = os.path.join(ROOT, "thesis_mcp_server.py")
    check("server present", os.path.isfile(server), server)
    styles = os.path.join(ROOT, "styles.json")
    check("styles.json present", os.path.isfile(styles), styles)

    print("[2] interpreter")
    try:
        r = run([args.python, "-c",
                 "import originpro, sys; print(sys.version.split()[0])"])
        ver = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        check("import originpro", r.returncode == 0,
              ("python " + ver) if r.returncode == 0
              else (r.stderr or "").strip().splitlines()[-1:] and
                   (r.stderr or "").strip().splitlines()[-1] or "import failed")
    except Exception as exc:                      # noqa: BLE001
        check("import originpro", False, "could not run interpreter: %s" % exc)

    print("[3] --info")
    info = {}
    if launcher:
        inv = launcher_invocation(launcher, ["--info"])
        r = run(inv)
        try:
            info = json.loads(r.stdout)
        except Exception:                         # noqa: BLE001
            info = {}
        check("--info returns JSON", bool(info),
              "" if info else ("stderr: " +
                               (r.stderr or "").strip()[:120]))
        if info:
            check("info.ok", info.get("ok"), str(info.get("ok")))
            check("originpro available", info.get("originpro"),
                  "python %s" % info.get("python"))
            check("batch_dir resolved", bool(info.get("batch_dir")),
                  str(info.get("batch_dir")))
            scripts = info.get("scripts") or {}
            missing = sorted(k for k in EXPECTED_SCRIPTS
                             if not (scripts.get(k) or {}).get("exists"))
            check("plotting scripts found", not missing,
                  "missing: %s" % missing if missing else "all 3 present")
            profs = set(info.get("profiles") or [])
            check("style profiles load", EXPECTED_PROFILES <= profs,
                  ",".join(sorted(profs)))

    print("[4] --list-tools")
    if launcher:
        r = run(launcher_invocation(launcher, ["--list-tools"]))
        try:
            reg = json.loads(r.stdout)
        except Exception:                         # noqa: BLE001
            reg = {}
        got = set(reg)
        check("expected tool set registered", got == EXPECTED_TOOLS,
              ("%d tools" % len(got)) if got == EXPECTED_TOOLS
              else "got %d, missing %s, extra %s"
                   % (len(got), sorted(EXPECTED_TOOLS - got),
                      sorted(got - EXPECTED_TOOLS)))
        # --list-tools maps each tool name to its own JSON Schema.
        bad_schema = [n for n, v in reg.items()
                      if (v or {}).get("type") != "object"
                      or not isinstance((v or {}).get("properties"), dict)]
        check("every tool exposes an object schema", not bad_schema,
              str(bad_schema))
        # A schema whose params all degraded to "string" means the annotations
        # were lost (e.g. reintroducing `from __future__ import annotations`),
        # which misleads the model about argument types.
        typed = [n for n, v in reg.items()
                 for t in ((v or {}).get("properties") or {}).values()
                 if (t or {}).get("type") in ("integer", "number", "boolean",
                                              "array", "object")]
        check("parameter types survive introspection", bool(typed),
              "%d typed parameters found" % len(typed))

    print("[5] MCP stdio handshake")
    if args.skip_handshake:
        print("  SKIP %-44s --skip-handshake" % "initialize/tools/call")
    elif not os.path.isfile(server):
        print("  SKIP %-44s server file missing (see [1])" % "initialize/tools/call")
    else:
        ok, detail = handshake(args.python, server)
        check("initialize -> tools/list -> tools/call", ok, detail)

    failed = [n for n, ok, _ in _results if not ok]
    print("")
    if failed:
        print("RESULT: %d/%d checks failed -> %s"
              % (len(failed), len(_results), ", ".join(failed)))
        print("")
        print("Next steps:")
        print("  * 'import originpro' failing  -> pip install originpro numpy Pillow")
        print("    (OriginLab ships wheels up to python 3.9 only)")
        print("  * batch_dir / scripts failing -> set DSH_THESIS_BATCH_DIR to your")
        print("    own checkout, or keep the vendored scripts next to the server")
        print("  * tools missing in DSH        -> restart the harness; check the")
        print("    profile bundles list and cordis.patch.yml")
        return 1
    print("RESULT: all %d checks passed." % len(_results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
