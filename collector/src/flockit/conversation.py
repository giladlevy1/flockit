"""Turn Claude Code transcript entries (JSONL on disk, or ``--output-format stream-json``)
into redacted conversation messages, token usage and files touched.

Everything that leaves the machine through this module passes ``redact_text``:
credentials are scrubbed and absolute paths are rewritten relative to the repository
(or to ``~``), so usernames and directory layouts are not sent.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from flockit.redact import scrub

MAX_TEXT = 20_000
MAX_TOOL_INPUT = 4_000
MAX_TOOL_RESULT = 4_000
MAX_TITLE = 200

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Claude Code writes these into the transcript as user messages; they are not the person's words.
META_PREFIXES = ("<command-name>", "<command-message>", "<local-command-stdout>", "<system-reminder>", "Caveat:")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… [{len(text) - limit} more characters]"


# Anyone's home directory, not just this machine's: /Users/alice, /home/bob, C:\Users\carol.
_OTHER_HOME = re.compile(r"(?:/Users|/home|/var/root|[A-Za-z]:\\Users)[/\\][^/\\\s\"']{1,64}")
# Volume and mount names can carry a customer's name.
_MOUNT = re.compile(r"/(?:Volumes|mnt|media)/[^/\s\"']{1,64}")


class PathRewriter:
    """Rewrites absolute paths: the repository root becomes ``.``, this machine's home ``~``,
    anyone else's home ``~other``, and other mounts a placeholder. Usernames and directory
    layouts never leave the machine."""

    def __init__(self, repo_root: Optional[str]) -> None:
        self.prefixes = []
        if repo_root:
            self.prefixes.append((repo_root.rstrip("/"), "."))
        home = os.path.expanduser("~")
        if home and home != "/":
            self.prefixes.append((home.rstrip("/"), "~"))

    def __call__(self, text: str) -> str:
        for old, new in self.prefixes:
            # Only at a path boundary, so /Users/mymacbook is not turned into ~book.
            text = re.sub(re.escape(old) + r"(?=[/\s\"'`,;:)\]}]|$)", new, text)
        text = _OTHER_HOME.sub("~other", text)
        return _MOUNT.sub("/mount", text)

    def relative(self, path: str) -> str:
        rewritten = self(path)
        return rewritten[2:] if rewritten.startswith("./") else rewritten


def redact_text(text: str, paths: PathRewriter, limit: int) -> str:
    return _clip(scrub(paths(text)), limit)


@dataclass
class Batch:
    """What one read of a transcript produced."""

    messages: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    files: Dict[str, int] = field(default_factory=dict)
    title: Optional[str] = None
    model: Optional[str] = None
    version: Optional[str] = None
    result: Optional[Dict[str, Any]] = None  # stream-json "result" event (headless runs)

    def empty(self) -> bool:
        return not (self.messages or any(self.usage.values()) or self.files or self.title)

    def payload(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "messages": self.messages,
            "usage": self.usage,
            "files": [{"path": p, "edits": n} for p, n in self.files.items()],
        }


class Converter:
    """Stateful across calls: remembers tool names by id and which API messages were counted."""

    def __init__(self, repo_root: Optional[str], state: Optional[Dict[str, Any]] = None) -> None:
        self.paths = PathRewriter(repo_root)
        state = state or {}
        self.seq: int = int(state.get("seq", 0))
        self.tools: Dict[str, str] = dict(state.get("tools", {}))
        self.counted: List[str] = list(state.get("counted", []))
        self.titled: bool = bool(state.get("titled", False))

    def state(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "tools": dict(list(self.tools.items())[-200:]),
            "counted": self.counted[-200:],
            "titled": self.titled,
        }

    # --- helpers ------------------------------------------------------------

    def _add(self, batch: Batch, entry_id: str, role: str, kind: str, content: str, at: str, tool: Optional[str] = None) -> None:
        if not content.strip():
            return
        batch.messages.append(
            {
                "id": entry_id[:64],
                "seq": self.seq,
                "role": role,
                "kind": kind,
                "tool_name": tool[:80] if tool else None,
                "content": content,
                "at": at or _now_iso(),
            }
        )
        self.seq += 1

    def _tool_input(self, name: str, data: Any) -> str:
        if not isinstance(data, dict):
            return redact_text(str(data), self.paths, MAX_TOOL_INPUT)
        if name == "Bash" and isinstance(data.get("command"), str):
            text = data["command"]
            if data.get("description"):
                text = f"# {data['description']}\n{text}"
            return redact_text(text, self.paths, MAX_TOOL_INPUT)
        if name in EDIT_TOOLS | {"Read"} and isinstance(data.get("file_path"), str):
            text = self.paths.relative(data["file_path"])
            if name == "Edit" and isinstance(data.get("old_string"), str):
                # Scrub before truncating: cutting first could leave half a credential behind.
                text += "\n--- replace\n" + _clip(scrub(data["old_string"]), 1500)
                text += "\n+++ with\n" + _clip(scrub(str(data.get("new_string", ""))), 1500)
            elif name == "Write" and isinstance(data.get("content"), str):
                text += f"\n({len(data['content'])} characters written)"
            return redact_text(text, self.paths, MAX_TOOL_INPUT)
        compact = {k: (_clip(scrub(v), 500) if isinstance(v, str) else v) for k, v in data.items()}
        return redact_text(json.dumps(compact, ensure_ascii=False, default=str), self.paths, MAX_TOOL_INPUT)

    @staticmethod
    def _result_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, dict) and block.get("type") == "image":
                    parts.append("[image]")
            return "\n".join(parts)
        return "" if content is None else str(content)

    # --- entries ------------------------------------------------------------

    def feed(self, entries: Iterable[Dict[str, Any]], batch: Optional[Batch] = None) -> Batch:
        batch = batch or Batch()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type")
            if isinstance(entry.get("version"), str):
                batch.version = entry["version"]
            if etype == "result":
                batch.result = entry
                continue
            if etype not in ("user", "assistant") or entry.get("isSidechain") or entry.get("isMeta"):
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            uid = str(entry.get("uuid") or message.get("id") or f"x{self.seq}")
            at = str(entry.get("timestamp") or "")
            content = message.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
            if not isinstance(blocks, list):
                continue

            if etype == "assistant":
                model = message.get("model")
                if isinstance(model, str) and model and not model.startswith("<"):
                    batch.model = model
                mid = message.get("id")
                usage = message.get("usage")
                if isinstance(usage, dict) and mid and mid not in self.counted:
                    self.counted.append(mid)
                    batch.usage["input"] += int(usage.get("input_tokens") or 0)
                    batch.usage["output"] += int(usage.get("output_tokens") or 0)
                    batch.usage["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                    batch.usage["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)

            for i, block in enumerate(blocks):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                bid = f"{uid}:{i}"
                if btype == "text":
                    text = str(block.get("text") or "")
                    if etype == "user":
                        if text.lstrip().startswith(META_PREFIXES):
                            continue
                        if not self.titled and text.strip():
                            batch.title = redact_text(" ".join(text.split()), self.paths, MAX_TITLE)
                            self.titled = True
                    self._add(batch, bid, etype, "text", redact_text(text, self.paths, MAX_TEXT), at)
                elif btype == "tool_use" and etype == "assistant":
                    name = str(block.get("name") or "tool")
                    if block.get("id"):
                        self.tools[str(block["id"])] = name
                    data = block.get("input")
                    if name in EDIT_TOOLS and isinstance(data, dict) and isinstance(data.get("file_path"), str):
                        rel = scrub(self.paths.relative(data["file_path"]))[:500]
                        if rel.startswith(("/", "~")) or ":\\" in rel:
                            rel = ".../" + "/".join(rel.replace("\\", "/").split("/")[-2:])  # outside the repo: last segments only
                        batch.files[rel] = batch.files.get(rel, 0) + 1
                    self._add(batch, bid, "assistant", "tool_use", self._tool_input(name, data), at, name)
                elif btype == "tool_result":
                    name = self.tools.get(str(block.get("tool_use_id")), None)
                    text = self._result_text(block.get("content"))
                    if block.get("is_error"):
                        text = "[error] " + text
                    self._add(batch, bid, "user", "tool_result", redact_text(text, self.paths, MAX_TOOL_RESULT), at, name)
        return batch


def read_new(path: str, offset: int, max_bytes: int = 4 * 1024 * 1024) -> tuple[List[Dict[str, Any]], int]:
    """Complete JSONL lines appended since ``offset``. Returns ``(entries, new_offset)``."""
    entries: List[Dict[str, Any]] = []
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read(max_bytes)
    except OSError:
        return entries, offset
    end = chunk.rfind(b"\n")
    if end < 0:
        return entries, offset  # no complete line yet
    for line in chunk[: end + 1].splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries, offset + end + 1
