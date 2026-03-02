"""Wrapper for nb CLI commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Note:
    """Represents an nb note."""

    id: str
    filename: str
    path: Path
    title: str | None
    notebook: str

    @property
    def selector(self) -> str:
        """Return the full selector for this note."""
        return f"{self.notebook}:{self.id}"


@dataclass
class Notebook:
    """Represents an nb notebook."""

    name: str
    path: Path


class NbError(Exception):
    """Error from nb command."""

    pass


class NbClient:
    """Client for interacting with nb CLI."""

    def __init__(self, nb_path: str = "nb", timeout: float = 5.0):
        self.nb_path = nb_path
        self.timeout = timeout
        self._notebooks_cache: list[Notebook] | None = None
        self._notes_cache: dict[str, list[Note]] = {}
        self._shutting_down = False

    async def _run(
        self, *args: str, check: bool = True
    ) -> asyncio.subprocess.Process:
        """Run an nb command and return stdout."""
        if self._shutting_down:
            raise NbError("Client is shutting down")

        cmd = [self.nb_path, *args]
        logger.debug(f"Running: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            async with asyncio.timeout(self.timeout):
                stdout, stderr = await proc.communicate()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise NbError("nb command timed out")

        if check and proc.returncode != 0:
            raise NbError(f"nb command failed: {stderr.decode()}")

        return _CompletedProcess(
            returncode=proc.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

    def shutdown(self):
        """Signal shutdown to prevent new operations."""
        self._shutting_down = True

    async def get_notebooks(self, use_cache: bool = True) -> list[Notebook]:
        """Get all notebooks."""
        if use_cache and self._notebooks_cache is not None:
            return self._notebooks_cache

        result = await self._run("notebooks", "--names", "--unarchived")
        notebooks = []

        for line in result.stdout.strip().split("\n"):
            name = line.strip()
            if name:
                path_result = await self._run(
                    "notebooks", "show", name, "--path", check=False
                )
                if path_result.returncode == 0:
                    path = Path(path_result.stdout.strip())
                    notebooks.append(Notebook(name=name, path=path))

        self._notebooks_cache = notebooks
        return notebooks

    async def get_notes(self, notebook: str, use_cache: bool = True) -> list[Note]:
        """Get all notes in a notebook."""
        if use_cache and notebook in self._notes_cache:
            return self._notes_cache[notebook]

        result = await self._run(
            f"{notebook}:",
            "list",
            "--no-indicator",
            "--filenames",
            "-n",
            "0",
            check=False,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to list notes in {notebook}: {result.stderr}")
            return []

        notes = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            note = await self._parse_list_line(line, notebook)
            if note:
                notes.append(note)

        self._notes_cache[notebook] = notes
        return notes

    async def _parse_list_line(self, line: str, notebook: str) -> Note | None:
        """Parse a line from nb list output."""
        import re

        match = re.match(r'\[(\d+)\]\s+(\S+)(?:\s+"([^"]*)")?', line)
        if not match:
            return None

        note_id = match.group(1)
        filename = match.group(2)
        title = match.group(3)

        path_result = await self._run(
            "show", f"{notebook}:{note_id}", "--path", check=False
        )

        if path_result.returncode != 0:
            return None

        path = Path(path_result.stdout.strip())

        return Note(
            id=note_id,
            filename=filename,
            path=path,
            title=title,
            notebook=notebook,
        )

    async def resolve_selector(
        self, selector: str, current_notebook: str | None = None
    ) -> Path | None:
        """Resolve a selector to a file path."""
        if ":" not in selector and current_notebook:
            selector = f"{current_notebook}:{selector}"

        result = await self._run("show", selector, "--path", check=False)

        if result.returncode != 0:
            return None

        path_str = result.stdout.strip()
        if path_str:
            return Path(path_str)
        return None

    async def get_tags(self, notebook: str | None = None) -> list[str]:
        """Get all tags, optionally filtered by notebook."""
        args = ["tags", "--list"]
        if notebook:
            args.insert(0, f"{notebook}:")

        result = await self._run(*args, check=False)

        if result.returncode != 0:
            return []

        tags = []
        for line in result.stdout.strip().split("\n"):
            tag = line.strip().lstrip("#")
            if tag:
                tags.append(tag)

        return tags

    async def get_current_notebook(self, file_path: Path) -> str | None:
        """Determine which notebook a file belongs to."""
        notebooks = await self.get_notebooks()

        for nb in notebooks:
            try:
                file_path.relative_to(nb.path)
                return nb.name
            except ValueError:
                continue

        return None

    def invalidate_cache(self, notebook: str | None = None):
        """Invalidate cached data."""
        if notebook:
            self._notes_cache.pop(notebook, None)
        else:
            self._notebooks_cache = None
            self._notes_cache.clear()


@dataclass
class _CompletedProcess:
    """Simple container for subprocess result."""

    returncode: int
    stdout: str
    stderr: str
