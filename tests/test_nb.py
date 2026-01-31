"""Tests for the nb client module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nb_lsp.nb import NbClient, NbError, Note, Notebook


class TestNbClient:
    """Tests for NbClient class."""

    @pytest.fixture
    def client(self):
        """Create a fresh NbClient instance."""
        return NbClient()

    @pytest.fixture
    def mock_run(self):
        """Create a mock for subprocess.run."""
        with patch("subprocess.run") as mock:
            yield mock

    def test_run_success(self, client, mock_run):
        """Test successful command execution."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "test"],
            returncode=0,
            stdout="output",
            stderr="",
        )

        result = client._run("test")

        assert result.stdout == "output"
        mock_run.assert_called_once()

    def test_run_failure(self, client, mock_run):
        """Test command failure raises NbError."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "test"],
            returncode=1,
            stdout="",
            stderr="error message",
        )

        with pytest.raises(NbError, match="error message"):
            client._run("test")

    def test_run_timeout(self, client, mock_run):
        """Test command timeout raises NbError."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="nb", timeout=30)

        with pytest.raises(NbError, match="timed out"):
            client._run("test")

    def test_run_not_found(self, client, mock_run):
        """Test command not found raises NbError."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(NbError, match="not found"):
            client._run("test")

    def test_get_notebooks(self, client, mock_run):
        """Test getting list of notebooks."""
        # First call: list notebooks
        # Second+ calls: get paths for each notebook
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "--names", "--no-archived"],
                returncode=0,
                stdout="home\nwork\npersonal\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "show", "home", "--path"],
                returncode=0,
                stdout="/home/user/.nb/home\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "show", "work", "--path"],
                returncode=0,
                stdout="/home/user/.nb/work\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "show", "personal", "--path"],
                returncode=0,
                stdout="/home/user/.nb/personal\n",
                stderr="",
            ),
        ]

        notebooks = client.get_notebooks(use_cache=False)

        assert len(notebooks) == 3
        assert notebooks[0].name == "home"
        assert notebooks[0].path == Path("/home/user/.nb/home")
        assert notebooks[1].name == "work"
        assert notebooks[2].name == "personal"

    def test_get_notebooks_caching(self, client, mock_run):
        """Test that notebooks are cached."""
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "--names", "--no-archived"],
                returncode=0,
                stdout="home\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["nb", "notebooks", "show", "home", "--path"],
                returncode=0,
                stdout="/home/user/.nb/home\n",
                stderr="",
            ),
        ]

        # First call
        notebooks1 = client.get_notebooks()
        # Second call should use cache
        notebooks2 = client.get_notebooks()

        assert notebooks1 == notebooks2
        # Should only have called subprocess twice (once for list, once for path)
        assert mock_run.call_count == 2

    def test_parse_list_line_with_title(self, client):
        """Test parsing a list line with title."""
        line = '[42] example.md "Example Title"'
        
        with patch.object(client, "_run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["nb", "show", "home:42", "--path"],
                returncode=0,
                stdout="/home/user/.nb/home/example.md\n",
                stderr="",
            )
            
            note = client._parse_list_line(line, "home")

        assert note is not None
        assert note.id == "42"
        assert note.filename == "example.md"
        assert note.title == "Example Title"
        assert note.notebook == "home"

    def test_parse_list_line_without_title(self, client):
        """Test parsing a list line without title."""
        line = "[123] notes.md"

        with patch.object(client, "_run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["nb", "show", "home:123", "--path"],
                returncode=0,
                stdout="/home/user/.nb/home/notes.md\n",
                stderr="",
            )

            note = client._parse_list_line(line, "home")

        assert note is not None
        assert note.id == "123"
        assert note.filename == "notes.md"
        assert note.title is None

    def test_parse_list_line_invalid(self, client):
        """Test parsing an invalid list line."""
        line = "not a valid line"
        note = client._parse_list_line(line, "home")

        assert note is None

    def test_resolve_selector_success(self, client, mock_run):
        """Test resolving a selector to a path."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "show", "home:My Note", "--path"],
            returncode=0,
            stdout="/home/user/.nb/home/my_note.md\n",
            stderr="",
        )

        path = client.resolve_selector("My Note", current_notebook="home")

        assert path == Path("/home/user/.nb/home/my_note.md")

    def test_resolve_selector_not_found(self, client, mock_run):
        """Test resolving a non-existent selector."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "show", "home:Nonexistent", "--path"],
            returncode=1,
            stdout="",
            stderr="Not found",
        )

        path = client.resolve_selector("Nonexistent", current_notebook="home")

        assert path is None

    def test_resolve_selector_with_notebook_prefix(self, client, mock_run):
        """Test resolving a selector that already has notebook prefix."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "show", "work:123", "--path"],
            returncode=0,
            stdout="/home/user/.nb/work/note.md\n",
            stderr="",
        )

        path = client.resolve_selector("work:123", current_notebook="home")

        assert path == Path("/home/user/.nb/work/note.md")
        # Should use the provided prefix, not current_notebook
        args_used = mock_run.call_args[0][0]
        assert "work:123" in args_used

    def test_get_tags(self, client, mock_run):
        """Test getting tags."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "tags", "--list"],
            returncode=0,
            stdout="#tag1\n#tag2\n#project/design\n",
            stderr="",
        )

        tags = client.get_tags()

        assert len(tags) == 3
        assert "tag1" in tags
        assert "tag2" in tags
        assert "project/design" in tags

    def test_get_tags_empty(self, client, mock_run):
        """Test getting tags when none exist."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nb", "tags", "--list"],
            returncode=0,
            stdout="",
            stderr="",
        )

        tags = client.get_tags()

        assert tags == []

    def test_get_current_notebook(self, client):
        """Test determining notebook from file path."""
        client._notebooks_cache = [
            Notebook(name="home", path=Path("/home/user/.nb/home")),
            Notebook(name="work", path=Path("/home/user/.nb/work")),
        ]

        # File in home notebook
        result = client.get_current_notebook(Path("/home/user/.nb/home/note.md"))
        assert result == "home"

        # File in work notebook, in subfolder
        result = client.get_current_notebook(
            Path("/home/user/.nb/work/projects/idea.md")
        )
        assert result == "work"

        # File not in any notebook
        result = client.get_current_notebook(Path("/tmp/random.md"))
        assert result is None

    def test_invalidate_cache_specific(self, client):
        """Test invalidating cache for specific notebook."""
        client._notebooks_cache = [Notebook(name="home", path=Path("/tmp"))]
        client._notes_cache = {
            "home": [Note(id="1", filename="a.md", path=Path("/tmp/a.md"), title=None, notebook="home")],
            "work": [Note(id="2", filename="b.md", path=Path("/tmp/b.md"), title=None, notebook="work")],
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
