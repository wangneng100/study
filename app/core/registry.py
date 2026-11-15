"""Tool registry.

A learning tool is a package under app/tools/ that exposes a module-level
`tool = Tool(...)`. It is found and mounted at /<slug>/ automatically, so adding
a tool never requires touching the rest of the app.
"""
import importlib
import pkgutil
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from flask import Blueprint


@dataclass(frozen=True)
class Tool:
    slug: str                 # URL prefix and blueprint name, e.g. "vocab"
    name: str                 # shown in the navigation and on the home page
    description: str          # one line for the home page
    blueprint: Blueprint      # the tool's pages and API
    schema: str = ""          # CREATE TABLE IF NOT EXISTS ... for the tool's tables
    # Optional one-line status for the home page, e.g. "3 个词该复习了".
    status: Optional[Callable[[sqlite3.Connection], str]] = None
    order: int = 100


def discover() -> list[Tool]:
    import app.tools as package

    tools = []
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        tool = getattr(module, "tool", None)
        if isinstance(tool, Tool):
            tools.append(tool)
    return sorted(tools, key=lambda t: (t.order, t.slug))
