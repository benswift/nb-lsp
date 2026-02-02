"""Tests for the LSP server module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from lsprotocol import types as lsp

from nb_lsp.nb import Note, Notebook
from nb_lsp.server import (
    NbLanguageServer,
    get_link_completions,
    get_tag_completions,
    offset_to_position,
    path_to_uri,
    position_to_offset,
    uri_to_path,
)


class TestUriPathConversion:
    """Tests for URI/path conversion functions."""

    def test_uri_to_path(self):
        """Test converting file URI to path."""
        uri = "file:///home/user/note.md"
        path = uri_to_path(uri)

        assert path == Path("/home/user/note.md")

    def test_uri_to_path_with_spaces(self):
        """Test converting URI with encoded spaces."""
        uri = "file:///home/user/my%20notes/note.md"
        path = uri_to_path(uri)

        assert path == Path("/home/user/my notes/note.md")

    def test_uri_to_path_non_file(self):
        """Test non-file URI returns None."""
        uri = "https://example.com/note.md"
        path = uri_to_path(uri)

        assert path is None

    def test_path_to_uri(self):
        """Test converting path to file URI."""
        path = Path("/home/user/note.md")
        uri = path_to_uri(path)

        assert uri == "file:///home/user/note.md"


class TestPositionOffset:
    """Tests for position/offset conversion."""

    @pytest.fixture
    def mock_document(self):
        """Create a mock document."""
        doc = MagicMock()
        doc.source = "Line one\nLine two\nLine three"
        return doc

    def test_position_to_offset_first_line(self, mock_document):
        """Test converting position on first line."""
        pos = lsp.Position(line=0, character=5)
        offset = position_to_offset(mock_document, pos)

        assert offset == 5
        assert mock_document.source[offset] == "o"

    def test_position_to_offset_second_line(self, mock_document):
        """Test converting position on second line."""
        pos = lsp.Position(line=1, character=0)
        offset = position_to_offset(mock_document, pos)

        assert offset == 9
        assert mock_document.source[offset] == "L"

    def test_position_to_offset_middle(self, mock_document):
        """Test converting position in middle of document."""
        pos = lsp.Position(line=1, character=5)
        offset = position_to_offset(mock_document, pos)

        assert offset == 14
        assert mock_document.source[offset] == "t"

    def test_offset_to_position_first_line(self, mock_document):
        """Test converting offset on first line."""
        pos = offset_to_position(mock_document, 5)

        assert pos.line == 0
        assert pos.character == 5

    def test_offset_to_position_second_line(self, mock_document):
        """Test converting offset on second line."""
        pos = offset_to_position(mock_document, 14)

        assert pos.line == 1
        assert pos.character == 5


class TestNbLanguageServer:
    """Tests for NbLanguageServer class."""

    @pytest.fixture
    def server(self):
        """Create a server instance with mocked nb client."""
        srv = NbLanguageServer("test", "v0.0.0")
        srv.nb = MagicMock()
        srv.nb.get_current_notebook = AsyncMock()
        srv.nb.get_notebooks = AsyncMock()
        srv.nb.get_notes = AsyncMock()
        return srv

    async def test_get_notebook_for_uri(self, server):
        """Test getting notebook for a URI."""
        server.nb.get_current_notebook.return_value = "home"

        result = await server.get_notebook_for_uri("file:///home/user/.nb/home/note.md")

        assert result == "home"

    async def test_get_all_notes(self, server):
        """Test getting all notes from all notebooks."""
        server.nb.get_notebooks.return_value = [
            Notebook(name="home", path=Path("/tmp/home")),
            Notebook(name="work", path=Path("/tmp/work")),
        ]
        server.nb.get_notes.side_effect = [
            [
                Note(
                    id="1",
                    filename="a.md",
                    path=Path("/tmp/a.md"),
                    title="Note A",
                    notebook="home",
                )
            ],
            [
                Note(
                    id="2",
                    filename="b.md",
                    path=Path("/tmp/b.md"),
                    title="Note B",
                    notebook="work",
                )
            ],
        ]

        notes = await server.get_all_notes()

        assert len(notes) == 2
        assert notes[0].title == "Note A"
        assert notes[1].title == "Note B"


class TestLinkCompletions:
    """Tests for get_link_completions function."""

    @pytest.fixture
    def server(self):
        """Create a server instance with mocked nb client."""
        srv = NbLanguageServer("test", "v0.0.0")
        srv.nb = MagicMock()
        srv.nb.get_notebooks = AsyncMock(
            return_value=[
                Notebook(name="home", path=Path("/tmp/home")),
                Notebook(name="work", path=Path("/tmp/work")),
            ]
        )
        srv.nb.get_notes = AsyncMock()
        srv.get_notebook_for_uri = AsyncMock(return_value="home")
        srv.get_all_notes = AsyncMock()
        return srv

    async def test_empty_partial_returns_all(self, server):
        """Test that empty partial returns all notes."""
        server.get_all_notes.return_value = [
            Note(
                id="1",
                filename="a.md",
                path=Path("/tmp/a.md"),
                title="Alpha",
                notebook="home",
            ),
            Note(
                id="2",
                filename="b.md",
                path=Path("/tmp/b.md"),
                title="Beta",
                notebook="work",
            ),
        ]

        items = await get_link_completions(server, "file:///tmp/home/test.md", "")

        labels = [item.label for item in items]
        assert "Alpha" in labels
        assert "Beta" in labels

    async def test_partial_filters_by_title(self, server):
        """Test that partial text filters by title."""
        server.get_all_notes.return_value = [
            Note(
                id="1",
                filename="a.md",
                path=Path("/tmp/a.md"),
                title="Alpha Note",
                notebook="home",
            ),
            Note(
                id="2",
                filename="b.md",
                path=Path("/tmp/b.md"),
                title="Beta Note",
                notebook="home",
            ),
        ]

        items = await get_link_completions(server, "file:///tmp/home/test.md", "Alp")

        labels = [item.label for item in items]
        assert "Alpha Note" in labels
        assert "Beta Note" not in labels

    async def test_notebook_prefix_completion(self, server):
        """Test notebook name completion."""
        server.get_all_notes.return_value = []

        items = await get_link_completions(server, "file:///tmp/home/test.md", "wo")

        labels = [item.label for item in items]
        assert "work:" in labels

    async def test_cross_notebook_prefix(self, server):
        """Test completion adds notebook prefix for other notebooks."""
        server.get_all_notes.return_value = [
            Note(
                id="1",
                filename="a.md",
                path=Path("/tmp/a.md"),
                title="Work Note",
                notebook="work",
            ),
        ]

        items = await get_link_completions(server, "file:///tmp/home/test.md", "")

        work_items = [item for item in items if item.label == "Work Note"]
        assert len(work_items) == 1
        assert work_items[0].insert_text == "work:Work Note"

    async def test_same_notebook_no_prefix(self, server):
        """Test completion doesn't add prefix for same notebook."""
        server.get_all_notes.return_value = [
            Note(
                id="1",
                filename="a.md",
                path=Path("/tmp/a.md"),
                title="Home Note",
                notebook="home",
            ),
        ]

        items = await get_link_completions(server, "file:///tmp/home/test.md", "")

        home_items = [item for item in items if item.label == "Home Note"]
        assert len(home_items) == 1
        assert home_items[0].insert_text == "Home Note"


class TestTagCompletions:
    """Tests for get_tag_completions function."""

    @pytest.fixture
    def server(self):
        """Create a server instance with mocked nb client."""
        srv = NbLanguageServer("test", "v0.0.0")
        srv.nb = MagicMock()
        srv.nb.get_tags = AsyncMock()
        return srv

    async def test_returns_all_tags(self, server):
        """Test that all tags are returned when partial is empty."""
        server.nb.get_tags.return_value = ["tag1", "tag2", "project/design"]

        items = await get_tag_completions(server, "")

        labels = [item.label for item in items]
        assert "#tag1" in labels
        assert "#tag2" in labels
        assert "#project/design" in labels

    async def test_filters_by_partial(self, server):
        """Test that partial text filters tags."""
        server.nb.get_tags.return_value = ["alpha", "beta", "alphabet"]

        items = await get_tag_completions(server, "alp")

        labels = [item.label for item in items]
        assert "#alpha" in labels
        assert "#alphabet" in labels
        assert "#beta" not in labels

    async def test_insert_text_excludes_hash(self, server):
        """Test that insert_text doesn't include #."""
        server.nb.get_tags.return_value = ["mytag"]

        items = await get_tag_completions(server, "")

        assert items[0].label == "#mytag"
        assert items[0].insert_text == "mytag"


class TestDiagnostics:
    """Tests for diagnostic generation."""

    def test_broken_link_detection_logic(self):
        """Test the logic for detecting broken links."""
        from nb_lsp.selectors import parse_wiki_links

        text = "See [[Valid Note]] and [[Broken Link]]."
        links = parse_wiki_links(text)

        assert len(links) == 2
        assert links[0].selector == "Valid Note"
        assert links[1].selector == "Broken Link"


class TestShutdown:
    """Tests for shutdown handling."""

    def test_shutdown_calls_nb_shutdown(self):
        """Test that shutdown handler calls nb.shutdown()."""
        from nb_lsp.server import server, shutdown

        server.nb = MagicMock()
        server._shutting_down = False

        shutdown(None)

        server.nb.shutdown.assert_called_once()

    def test_shutdown_sets_flag(self):
        """Test that shutdown sets _shutting_down flag."""
        from nb_lsp.server import server, shutdown

        server._shutting_down = False
        server.nb = MagicMock()

        shutdown(None)

        assert server._shutting_down is True

    async def test_completions_returns_none_when_shutting_down(self):
        """Test that completions returns early when shutting down."""
        from nb_lsp.server import completions, server

        server._shutting_down = True
        server.nb = MagicMock()
        server.nb.get_notebooks = AsyncMock()

        params = MagicMock()
        result = await completions(params)

        assert result is None
        server.nb.get_notebooks.assert_not_called()

    async def test_definition_returns_none_when_shutting_down(self):
        """Test that definition returns early when shutting down."""
        from nb_lsp.server import definition, server

        server._shutting_down = True
        server.nb = MagicMock()

        params = MagicMock()
        result = await definition(params)

        assert result is None

    async def test_diagnostics_returns_empty_when_shutting_down(self):
        """Test that diagnostics returns empty report when shutting down."""
        from nb_lsp.server import diagnostics, server

        server._shutting_down = True
        server.nb = MagicMock()

        params = MagicMock()
        result = await diagnostics(params)

        assert result.items == []
