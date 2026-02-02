"""Tests for the nb client module."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nb_lsp.nb import NbClient, NbError, Note, Notebook


class TestNbClient:
    """Tests for NbClient class."""

    @pytest.fixture
    def client(self):
        """Create a fresh NbClient instance."""
        return NbClient()

    def _make_mock_proc(self, stdout: str, stderr: str = "", returncode: int = 0):
        """Create a mock async process."""
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(stdout.encode(), stderr.encode())
        )
        mock_proc.returncode = returncode
        mock_proc.kill = MagicMock()
        return mock_proc

    async def test_run_success(self, client):
        """Test successful command execution."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("output")

            result = await client._run("test")

            assert result.stdout == "output"
            mock_exec.assert_called_once()

    async def test_run_failure(self, client):
        """Test command failure raises NbError."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("", "error message", 1)

            with pytest.raises(NbError, match="error message"):
                await client._run("test")

    async def test_run_timeout(self, client):
        """Test command timeout raises NbError."""
        client.timeout = 0.001

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(
                side_effect=[asyncio.TimeoutError(), (b"", b"")]
            )
            mock_proc.kill = MagicMock()
            mock_exec.return_value = mock_proc

            with pytest.raises(NbError, match="timed out"):
                await client._run("test")

            mock_proc.kill.assert_called_once()

    async def test_run_when_shutting_down(self, client):
        """Test that _run raises NbError when shutting down."""
        client._shutting_down = True

        with pytest.raises(NbError, match="shutting down"):
            await client._run("test")

    async def test_get_notebooks(self, client):
        """Test getting list of notebooks."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = [
                self._make_mock_proc("home\nwork\npersonal\n"),
                self._make_mock_proc("/home/user/.nb/home\n"),
                self._make_mock_proc("/home/user/.nb/work\n"),
                self._make_mock_proc("/home/user/.nb/personal\n"),
            ]

            notebooks = await client.get_notebooks(use_cache=False)

            assert len(notebooks) == 3
            assert notebooks[0].name == "home"
            assert notebooks[0].path == Path("/home/user/.nb/home")
            assert notebooks[1].name == "work"
            assert notebooks[2].name == "personal"

    async def test_get_notebooks_caching(self, client):
        """Test that notebooks are cached."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = [
                self._make_mock_proc("home\n"),
                self._make_mock_proc("/home/user/.nb/home\n"),
            ]

            notebooks1 = await client.get_notebooks()
            notebooks2 = await client.get_notebooks()

            assert notebooks1 == notebooks2
            assert mock_exec.call_count == 2

    async def test_parse_list_line_with_title(self, client):
        """Test parsing a list line with title."""
        line = '[42] example.md "Example Title"'

        with patch.object(client, "_run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="/home/user/.nb/home/example.md\n",
            )

            note = await client._parse_list_line(line, "home")

        assert note is not None
        assert note.id == "42"
        assert note.filename == "example.md"
        assert note.title == "Example Title"
        assert note.notebook == "home"

    async def test_parse_list_line_without_title(self, client):
        """Test parsing a list line without title."""
        line = "[123] notes.md"

        with patch.object(client, "_run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="/home/user/.nb/home/notes.md\n",
            )

            note = await client._parse_list_line(line, "home")

        assert note is not None
        assert note.id == "123"
        assert note.filename == "notes.md"
        assert note.title is None

    async def test_parse_list_line_invalid(self, client):
        """Test parsing an invalid list line."""
        line = "not a valid line"
        note = await client._parse_list_line(line, "home")

        assert note is None

    async def test_resolve_selector_success(self, client):
        """Test resolving a selector to a path."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("/home/user/.nb/home/my_note.md\n")

            path = await client.resolve_selector("My Note", current_notebook="home")

            assert path == Path("/home/user/.nb/home/my_note.md")

    async def test_resolve_selector_not_found(self, client):
        """Test resolving a non-existent selector."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("", "Not found", 1)

            path = await client.resolve_selector("Nonexistent", current_notebook="home")

            assert path is None

    async def test_resolve_selector_with_notebook_prefix(self, client):
        """Test resolving a selector that already has notebook prefix."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("/home/user/.nb/work/note.md\n")

            path = await client.resolve_selector("work:123", current_notebook="home")

            assert path == Path("/home/user/.nb/work/note.md")

    async def test_get_tags(self, client):
        """Test getting tags."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("#tag1\n#tag2\n#project/design\n")

            tags = await client.get_tags()

            assert len(tags) == 3
            assert "tag1" in tags
            assert "tag2" in tags
            assert "project/design" in tags

    async def test_get_tags_empty(self, client):
        """Test getting tags when none exist."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = self._make_mock_proc("")

            tags = await client.get_tags()

            assert tags == []

    def test_shutdown_sets_flag(self, client):
        """Test that shutdown sets the shutting down flag."""
        assert client._shutting_down is False
        client.shutdown()
        assert client._shutting_down is True

    async def test_get_current_notebook(self, client):
        """Test determining notebook from file path."""
        client._notebooks_cache = [
            Notebook(name="home", path=Path("/home/user/.nb/home")),
            Notebook(name="work", path=Path("/home/user/.nb/work")),
        ]

        result = await client.get_current_notebook(Path("/home/user/.nb/home/note.md"))
        assert result == "home"

        result = await client.get_current_notebook(
            Path("/home/user/.nb/work/projects/idea.md")
        )
        assert result == "work"

        result = await client.get_current_notebook(Path("/tmp/random.md"))
        assert result is None

    def test_invalidate_cache_specific(self, client):
        """Test invalidating cache for specific notebook."""
        client._notebooks_cache = [Notebook(name="home", path=Path("/tmp"))]
        client._notes_cache = {
            "home": [
                Note(
                    id="1",
                    filename="a.md",
                    path=Path("/tmp/a.md"),
                    title=None,
                    notebook="home",
                )
            ],
            "work": [
                Note(
                    id="2",
                    filename="b.md",
                    path=Path("/tmp/b.md"),
                    title=None,
                    notebook="work",
                )
            ],
        }

        client.invalidate_cache("home")

        assert "home" not in client._notes_cache
        assert "work" in client._notes_cache
        assert client._notebooks_cache is not None

    def test_invalidate_cache_all(self, client):
        """Test invalidating all caches."""
        client._notebooks_cache = [Notebook(name="home", path=Path("/tmp"))]
        client._notes_cache = {"home": [], "work": []}

        client.invalidate_cache()

        assert client._notebooks_cache is None
        assert client._notes_cache == {}


class TestNote:
    """Tests for Note dataclass."""

    def test_selector_property(self):
        """Test the selector property."""
        note = Note(
            id="42",
            filename="example.md",
            path=Path("/tmp/example.md"),
            title="Example",
            notebook="home",
        )

        assert note.selector == "home:42"

    def test_note_without_title(self):
        """Test note without a title."""
        note = Note(
            id="1",
            filename="untitled.md",
            path=Path("/tmp/untitled.md"),
            title=None,
            notebook="work",
        )

        assert note.title is None
        assert note.selector == "work:1"
