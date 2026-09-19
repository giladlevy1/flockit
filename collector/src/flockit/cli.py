"""``flockit`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from flockit import __version__, claude_settings, config, outbox, transport


def _cmd_install(args: argparse.Namespace) -> int:
    server = (args.server or os.environ.get("FLOCKIT_SERVER") or "").strip().rstrip("/")
    token = (args.token or os.environ.get("FLOCKIT_TOKEN") or "").strip()
    if not server or not token:
        print("flockit install needs --server and --token (copy the command from the Connect page).", file=sys.stderr)
        return 2
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    cfg = config.Config(server_url=server, token=token)

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
    print("Your next Claude Code session will appear in Flockit. Nothing else to configure.")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    path = claude_settings.uninstall()
    config.delete()
    print("Removed Flockit hooks from %s and deleted the local config." % path)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    print("flockit collector %s" % __version__)
    print("  config:   %s" % ("%s" % cfg.server_url if cfg else "not configured (run flockit install)"))
    print("  hooks:    %s" % ("installed" if claude_settings.installed() else "not installed"))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flockit", description="Flockit collector for Claude Code.")
    parser.add_argument("--version", action="version", version="flockit " + __version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("install", help="connect to a Flockit server and register Claude Code hooks")
    p.add_argument("--server", help="your Flockit server URL, e.g. http://flockit.internal:8080")
    p.add_argument("--token", help="a collector token from the Connect page")
    p.add_argument("--skip-verify", action="store_true", help="do not check the server before saving")
    p.set_defaults(func=_cmd_install)

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
