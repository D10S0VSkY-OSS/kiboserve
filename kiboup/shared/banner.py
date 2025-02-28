"""Startup banner and host/import utilities for kiboup."""

import os
import sys
from typing import Any, List, Optional


def detect_host() -> str:
    """Detect host: 0.0.0.0 for Docker, 127.0.0.1 otherwise."""
    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER"):
        return "0.0.0.0"
    return "127.0.0.1"


def resolve_import_string(app_instance: Any) -> Optional[str]:
    """Resolve the import string for an app instance (e.g. 'examples.my_app:app').

    Required by uvicorn when using ``workers > 1`` or ``reload=True``,
    since the application must be importable by each subprocess.

    Returns None if the import string cannot be determined.
    """
    main = sys.modules.get("__main__")
    if not main or not getattr(main, "__file__", None):
        return None

    var_name = None
    for name, obj in vars(main).items():
        if obj is app_instance and not name.startswith("_"):
            var_name = name
            break
    if not var_name:
        return None

    file_path = os.path.abspath(main.__file__)
    cwd = os.getcwd()
    if not file_path.startswith(cwd):
        return None

    rel = os.path.relpath(file_path, cwd)
    module = rel.replace(os.sep, ".").removesuffix(".py")
    return f"{module}:{var_name}"


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

_BANNER_WIDTH = 58

_BANNER_ART: List[str] = [
    r" _  __ _ _                       ",
    r"| |/ /(_) |__   ___  _   _ _ __  ",
    r"| ' / | | '_ \ / _ \| | | | '_ \ ",
    r"| . \ | | |_) | (_) | |_| | |_) |",
    r"|_|\_\|_|_.__/ \___/ \__,_| .__/ ",
    r"                          |_|    ",
]

_GRADIENT_RGB: List[tuple] = [
    (155, 89, 182),
    (180, 70, 160),
    (210, 60, 130),
    (230, 90, 80),
    (240, 140, 40),
    (243, 180, 18),
]

_BORDER_RGB = (100, 100, 120)


def _rgb(r: int, g: int, b: int, text: str) -> str:
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def _border(text: str, is_tty: bool) -> str:
    if is_tty:
        return _rgb(*_BORDER_RGB, text)
    return text


def _center_line(content: str, width: int) -> str:
    padding = max(width - len(content), 0)
    left = padding // 2
    right = padding - left
    return " " * left + content + " " * right


def _terminal_width() -> int:
    """Detect terminal width with fallback to 80."""
    try:
        return os.get_terminal_size(sys.stderr.fileno()).columns
    except (OSError, ValueError, AttributeError):
        return 80


def print_banner(mode: str, host: str, port: int):
    """Print the KiboUp ASCII banner centered on the terminal."""
    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    w = _BANNER_WIDTH
    inner = w - 4
    term_w = _terminal_width()
    margin = " " * max((term_w - w) // 2, 0)

    top = _border("+" + "-" * (w - 2) + "+", is_tty)
    bot = top
    pipe_l = _border("| ", is_tty)
    pipe_r = _border(" |", is_tty)
    empty = _border("|", is_tty) + " " * (w - 2) + _border("|", is_tty)

    out = sys.stderr.write

    out("\n")
    out(margin + top + "\n")
    out(margin + empty + "\n")

    for i, line in enumerate(_BANNER_ART):
        padded = _center_line(line, inner)
        color = _GRADIENT_RGB[i % len(_GRADIENT_RGB)]
        if is_tty:
            out(margin + pipe_l + _rgb(*color, padded) + pipe_r + "\n")
        else:
            out(margin + pipe_l + padded + pipe_r + "\n")

    out(margin + empty + "\n")

    dim = "\033[2m" if is_tty else ""
    cyan = "\033[36m" if is_tty else ""
    reset = "\033[0m" if is_tty else ""

    mode_text = f"{dim}Mode:{reset} {cyan}{mode}{reset}"
    host_text = f"{dim}Host:{reset} {cyan}{host}:{port}{reset}"

    mode_raw = f"Mode: {mode}"
    host_raw = f"Host: {host}:{port}"

    mode_pad = _center_line(mode_raw, inner)
    host_pad = _center_line(host_raw, inner)

    if is_tty:
        mode_padded = _center_line("", (inner - len(mode_raw)) // 2) + mode_text + " " * (inner - len(mode_raw) - (inner - len(mode_raw)) // 2)
        host_padded = _center_line("", (inner - len(host_raw)) // 2) + host_text + " " * (inner - len(host_raw) - (inner - len(host_raw)) // 2)
        out(margin + pipe_l + mode_padded + pipe_r + "\n")
        out(margin + pipe_l + host_padded + pipe_r + "\n")
    else:
        out(margin + pipe_l + mode_pad + pipe_r + "\n")
        out(margin + pipe_l + host_pad + pipe_r + "\n")

    out(margin + empty + "\n")
    out(margin + bot + "\n")
    out("\n")
