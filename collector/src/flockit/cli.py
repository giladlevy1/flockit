"""``flockit`` command line."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import List, Optional

from flockit import __version__, claude_settings, config, outbox, service, transport


def _cmd_install(args: argparse.Namespace) -> int:
    server = (args.server or os.environ.get("FLOCKIT_SERVER") or "").strip().rstrip("/")
    token = (args.token or os.environ.get("FLOCKIT_TOKEN") or "").strip()
    if not server or not token:
        print("flockit install needs --server and --token (copy the command from the Connect page).", file=sys.stderr)
        return 2
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    claude = shutil.which("claude")
    cfg = config.Config(server_url=server, token=token, claude_path=claude)

    if not args.skip_verify:
        result = transport.request(cfg, "GET", "/api/ingest/whoami", timeout=5.0)
        if not result.ok:
            if result.status == 401:
                print("The server rejected that token. Create a new one on the Connect page.", file=sys.stderr)
            else:
                print("Could not reach %s (%s)." % (server, result.error or result.status), file=sys.stderr)
                print("Check the URL, or re-run with --skip-verify to configure it anyway.", file=sys.stderr)
            return 1
        who = (result.body or {}).get("user", {})
        print("Connected to %s as %s." % (server, who.get("name") or who.get("email") or "you"))

    config.save(cfg)
    path = claude_settings.install()
    print("Registered Claude Code hooks in %s." % path)
    if not args.no_agent:
        started = service.install()
        if started:
            print("Started the Flockit agent (%s): tasks assigned to you can now start on this machine." % started)
        else:
            print("To receive tasks on this machine, keep `flockit agent run` running.")
    if not claude:
        print("Note: `claude` was not found on PATH. Install Claude Code to run tasks here.")
    print("Your next Claude Code session will appear in Flockit. Nothing else to configure.")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    service.uninstall()
    path = claude_settings.uninstall()
    config.delete()
    print("Removed Flockit hooks from %s and deleted the local config." % path)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    print("flockit collector %s" % __version__)
    print("  config:   %s" % ("%s" % cfg.server_url if cfg else "not configured (run flockit install)"))
    print("  hooks:    %s" % ("installed" if claude_settings.installed() else "not installed"))
    print("  agent:    %s" % service.status())
    print("  buffered: %d event(s) waiting to send" % outbox.pending())
    if cfg:
        result = transport.request(cfg, "GET", "/api/ingest/whoami", timeout=3.0)
        if result.ok:
            who = (result.body or {}).get("user", {})
            print("  server:   reachable, token belongs to %s" % (who.get("email") or "unknown"))
        else:
            print("  server:   %s" % ("token rejected" if result.status == 401 else "unreachable (%s)" % result.error))
            return 1
    return 0


def _cmd_flush(args: argparse.Namespace) -> int:
    cfg = config.load()
    if cfg is None:
        return 0
    sent = transport.flush(cfg)
    if not args.quiet:
        print("sent %d event(s), %d still buffered" % (sent, outbox.pending()))
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    from flockit import hook

    try:
        text = sys.stdin.read()
    except Exception:  # noqa: BLE001
        text = ""
    hook.run(text)
    return 0  # always succeed: the collector must never block a session


def _cmd_agent(args: argparse.Namespace) -> int:
    if args.action == "status":
        print("agent: %s" % service.status())
        return 0
    if args.action == "stop":
        service.uninstall()
        print("Stopped the Flockit agent. Tasks will wait until you run `flockit agent start`.")
        return 0
    if args.action == "start":
        started = service.install()
        print("Started %s." % started if started else "Could not install a background service here; run `flockit agent run`.")
        return 0 if started else 1
    cfg = config.load()
    if cfg is None:
        print("Not configured. Run the install command from your Flockit Connect page first.", file=sys.stderr)
        return 2
    from flockit.agent import Agent

    try:
        Agent(cfg).run_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    cfg = config.load()
    if cfg is None:
        print("Not configured.", file=sys.stderr)
        return 2
    if args.action in ("accept", "decline"):
        if not args.id:
            print("usage: flockit tasks %s <task-id>" % args.action, file=sys.stderr)
            return 2
        body = {"interactive": not args.headless} if args.action == "accept" else None
        result = transport.request(cfg, "POST", "/api/agent/tasks/%s/%s" % (args.id, args.action), body or {}, timeout=10)
        print("Task %s: %s" % (args.id[:8], (result.body or {}).get("status") or (result.body or {}).get("detail") or result.error))
        return 0 if result.ok else 1
    result = transport.request(cfg, "GET", "/api/agent/tasks", timeout=10)
    if not result.ok:
        print("Could not reach Flockit: %s" % (result.error or result.status), file=sys.stderr)
        return 1
    tasks = (result.body or {}).get("tasks") or []
    if not tasks:
        print("No tasks waiting for you.")
    for t in tasks:
        print("%s  %-9s  %s  (%s)" % (t["id"], t["status"], t["title"], t.get("repo") or "no repo"))
    return 0


def _cmd_runner(args: argparse.Namespace) -> int:
    from flockit import runner

    if args.action == "build-image":
        return runner.build_image(args.image)
    server = (args.server or os.environ.get("FLOCKIT_SERVER") or "").rstrip("/")
    token = args.token or os.environ.get("FLOCKIT_RUNNER_TOKEN") or ""
    if not server or not token:
        print("flockit runner needs --server and --token (create a runner in Flockit: AI developers → Runners).", file=sys.stderr)
        return 2
    if args.backend == "docker" and not shutil.which("docker"):
        print("Docker is not available. Install it, or use --backend local.", file=sys.stderr)
        return 2
    cfg = runner.RunnerConfig(
        server_url=server, token=token, backend=args.backend, image=args.image, capacity=args.capacity,
        name=args.name or "", allow_full_local=args.allow_full_local, clone_url=args.clone_url,
    )
    try:
        runner.Runner(cfg).run_forever()
    except KeyboardInterrupt:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flockit", description="Flockit collector for Claude Code.")
    parser.add_argument("--version", action="version", version="flockit " + __version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("install", help="connect to a Flockit server and register Claude Code hooks")
    p.add_argument("--server", help="your Flockit server URL, e.g. http://flockit.internal:8080")
    p.add_argument("--token", help="a collector token from the Connect page")
    p.add_argument("--skip-verify", action="store_true", help="do not check the server before saving")
    p.add_argument("--no-agent", action="store_true", help="do not install the background agent that runs tasks")
    p.set_defaults(func=_cmd_install)

    p = sub.add_parser("agent", help="the background agent that starts Flockit tasks on this machine")
    p.add_argument("action", choices=["run", "start", "stop", "status"], nargs="?", default="status")
    p.set_defaults(func=_cmd_agent)

    p = sub.add_parser("tasks", help="list, accept or decline tasks assigned to you")
    p.add_argument("action", choices=["list", "accept", "decline"], nargs="?", default="list")
    p.add_argument("id", nargs="?")
    p.add_argument("--headless", action="store_true", help="accept and run in the background instead of a terminal")
    p.set_defaults(func=_cmd_tasks)

    p = sub.add_parser("runner", help="run AI-developer tasks in sandboxes on this machine")
    p.add_argument("action", choices=["run", "build-image"], nargs="?", default="run")
    p.add_argument("--server", help="Flockit server URL")
    p.add_argument("--token", help="runner token (frn_...), or FLOCKIT_RUNNER_TOKEN")
    p.add_argument("--backend", choices=["docker", "local"], default=os.environ.get("FLOCKIT_RUNNER_BACKEND", "docker"))
    p.add_argument("--image", default=os.environ.get("FLOCKIT_SANDBOX_IMAGE", "flockit-sandbox:latest"))
    p.add_argument("--capacity", type=int, default=int(os.environ.get("FLOCKIT_RUNNER_CAPACITY", "1")))
    p.add_argument("--name", help="how this runner appears in Flockit")
    p.add_argument("--allow-full-local", action="store_true", help="local backend: honour the full-permission profile")
    p.add_argument("--clone-url", default=os.environ.get("FLOCKIT_CLONE_URL_TEMPLATE", ""),
                   help='clone URL template, e.g. "git@{host}:{path}.git" (default: https://{repo}.git)')
    p.set_defaults(func=_cmd_runner)

    p = sub.add_parser("uninstall", help="remove hooks and local config")
    p.set_defaults(func=_cmd_uninstall)

    p = sub.add_parser("status", help="show configuration and connectivity")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("flush", help="send buffered events now")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=_cmd_flush)

    p = sub.add_parser("hook", help=argparse.SUPPRESS)
    p.set_defaults(func=_cmd_hook)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)
