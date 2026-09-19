"""Opening an interactive Claude Code session in a terminal, and desktop notifications."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from flockit import config

# Claude Code session ids are UUIDs; anything else never reaches the command line.
SESSION_ID = re.compile(r"^[0-9a-fA-F][0-9a-fA-F\-]{7,63}$")


def task_dir(task_id: str) -> Path:
    path = config.home() / "tasks" / task_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def start_script(task_id: str, title: str, workdir: str, prompt: str, claude: str, resume: Optional[str] = None) -> Path:
    """A script that opens Claude Code in the task's worktree with the task as its first prompt.
    Everything is quoted: the prompt is read from a file, never interpolated into the shell.

    With ``resume``, it reopens that earlier Claude Code session instead of starting a new
    one, so continuing work picks up the context it had when it stopped."""
    folder = task_dir(task_id)
    prompt_file = folder / "prompt.md"
    prompt_file.write_text(prompt)
    script = folder / "start.sh"
    resume_flag = f" --resume {shlex.quote(resume)}" if resume and SESSION_ID.match(resume) else ""
    script.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(workdir)} || exit 1\n"
        f"export FLOCKIT_TASK_ID={shlex.quote(task_id)}\n"
        f"printf '\\033[1mFlockit task:\\033[0m %s\\n\\n' {shlex.quote(title)}\n"
        # --setting-sources user: ignore the repository's own .claude settings for this run.
        f"exec {shlex.quote(claude)} --setting-sources user{resume_flag} \"$(cat {shlex.quote(str(prompt_file))})\"\n"
    )
    script.chmod(0o700)
    return script


def _terminal_command(script: Path) -> Optional[List[str]]:
    override = os.environ.get("FLOCKIT_TERMINAL")
    if override:
        return shlex.split(override) + [str(script)]
    if sys.platform == "darwin":
        if os.environ.get("FLOCKIT_TERMINAL_APP", "").lower() == "iterm" and Path("/Applications/iTerm.app").exists():
            osa = (
                'tell application "iTerm" to create window with default profile command '
                + '"' + str(script).replace('"', '\\"') + '"'
            )
        else:
            osa = (
                'tell application "Terminal"\n  activate\n  do script '
                + '"' + str(script).replace('"', '\\"') + '"\nend tell'
            )
        return ["osascript", "-e", osa]
    for candidate, args in (
        ("x-terminal-emulator", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("konsole", ["-e"]),
        ("xfce4-terminal", ["-x"]),
        ("kitty", []),
        ("alacritty", ["-e"]),
        ("xterm", ["-e"]),
    ):
        if shutil.which(candidate):
            return [candidate, *args, str(script)]
    return None


def can_open_terminal() -> bool:
    return _terminal_command(Path("/bin/true")) is not None


def open_terminal(script: Path) -> bool:
    command = _terminal_command(script)
    if command is None:
        return False
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def notify(title: str, message: str) -> None:
    """Best effort desktop notification. Never raises."""
    try:
        if sys.platform == "darwin":
            def esc(s: str) -> str:
                return s.replace("\\", "\\\\").replace('"', '\\"')[:200]

            subprocess.Popen(
                ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}" sound name "Glass"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Flockit", title[:200], message[:400]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
