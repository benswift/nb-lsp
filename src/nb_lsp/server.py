"""LSP server for nb note-taking tool."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument

from .nb import NbClient, Note
from .selectors import (
    WikiLink,
    get_link_at_position,
    get_partial_link_content,
    get_partial_tag,
    is_inside_link_brackets,
    is_inside_tag,
    parse_wiki_links,
)

logger = logging.getLogger(__name__)


class NbLanguageServer(LanguageServer):
    """Language server for nb."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nb = NbClient()
        self._shutting_down = False

    def get_notebook_for_uri(self, uri: str) -> str | None:
        """Get the notebook name for a document URI."""
        path = uri_to_path(uri)
        if path:
            return self.nb.get_current_notebook(path)
        return None

    def get_all_notes(self) -> list[Note]:
        """Get all notes from all notebooks."""
        notes = []
        for notebook in self.nb.get_notebooks():
            notes.extend(self.nb.get_notes(notebook.name))
        return notes


def uri_to_path(uri: str) -> Path | None:
    """Convert a file URI to a Path."""
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    return None


def path_to_uri(path: Path) -> str:
    """Convert a Path to a file URI."""
    return path.as_uri()


def position_to_offset(document: TextDocument, position: lsp.Position) -> int:
    """Convert an LSP position to a character offset."""
    lines = document.source.split("\n")
    offset = sum(len(line) + 1 for line in lines[: position.line])
    offset += position.character
    return offset


def offset_to_position(document: TextDocument, offset: int) -> lsp.Position:
    """Convert a character offset to an LSP position."""
    lines = document.source.split("\n")
    current = 0
    for line_num, line in enumerate(lines):
        line_len = len(line) + 1  # +1 for newline
        if current + line_len > offset:
            return lsp.Position(line=line_num, character=offset - current)
        current += line_len
    # Past end of document
    return lsp.Position(line=len(lines) - 1, character=len(lines[-1]))


# Create the server instance
server = NbLanguageServer("nb-lsp", "v0.1.0")


@server.feature(lsp.INITIALIZE)
def initialize(params: lsp.InitializeParams) -> lsp.InitializeResult:
    """Handle initialize request."""
    logger.info("Initializing nb-lsp")

    return lsp.InitializeResult(
        capabilities=lsp.ServerCapabilities(
            text_document_sync=lsp.TextDocumentSyncOptions(
                open_close=True,
                change=lsp.TextDocumentSyncKind.Full,
                save=lsp.SaveOptions(include_text=True),
            ),
            completion_provider=lsp.CompletionOptions(
                trigger_characters=["[", "#"],
                resolve_provider=False,
            ),
            definition_provider=True,
            diagnostic_provider=lsp.DiagnosticOptions(
                inter_file_dependencies=False,
                workspace_diagnostics=False,
            ),
        ),
        server_info=lsp.ServerInfo(
            name="nb-lsp",
            version="0.1.0",
        ),
    )


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
@server.thread()
def completions(params: lsp.CompletionParams) -> lsp.CompletionList | None:
    """Provide completions for wiki-style links and tags."""
    if server._shutting_down:
        return None
    document = server.workspace.get_text_document(params.text_document.uri)
    offset = position_to_offset(document, params.position)
    text = document.source

    items: list[lsp.CompletionItem] = []

    # Check if we're inside a wiki link [[...]]
    if is_inside_link_brackets(text, offset):
        partial = get_partial_link_content(text, offset) or ""
        items = get_link_completions(server, params.text_document.uri, partial)

    # Check if we're in a tag #...
    elif is_inside_tag(text, offset):
        partial = get_partial_tag(text, offset) or ""
        items = get_tag_completions(server, partial)

    if items:
        return lsp.CompletionList(is_incomplete=False, items=items)

    return None


def get_link_completions(
    server: NbLanguageServer, uri: str, partial: str
) -> list[lsp.CompletionItem]:
    """Get completion items for wiki links."""
    items = []
    current_notebook = server.get_notebook_for_uri(uri)

    # Check if partial specifies a notebook
    notebook_filter = None
    selector_partial = partial

    if ":" in partial:
        notebook_filter, selector_partial = partial.split(":", 1)

    # Get notebooks for completion
    notebooks = server.nb.get_notebooks()

    # If user is typing a notebook prefix, offer notebook completions
    if partial and ":" not in partial:
        for nb in notebooks:
            if nb.name.lower().startswith(partial.lower()):
                items.append(
                    lsp.CompletionItem(
                        label=f"{nb.name}:",
                        kind=lsp.CompletionItemKind.Folder,
                        detail="Notebook",
                        insert_text=f"{nb.name}:",
                    )
                )

    # Get notes for completion
    notes_to_show = []

    if notebook_filter:
        # Only show notes from specified notebook
        matching_notebooks = [nb for nb in notebooks if nb.name == notebook_filter]
        for nb in matching_notebooks:
            notes_to_show.extend(server.nb.get_notes(nb.name))
    else:
        # Show notes from all notebooks, but prefer current
        notes_to_show = server.get_all_notes()

    # Filter and create completion items
    selector_lower = selector_partial.lower()

    for note in notes_to_show:
        # Match against title, filename, or id
        matches = False
        match_text = ""

        if note.title and selector_lower in note.title.lower():
            matches = True
            match_text = note.title
        elif selector_lower in note.filename.lower():
            matches = True
            match_text = note.filename
        elif selector_lower in note.id:
            matches = True
            match_text = note.id

        if not selector_partial:  # Show all if no filter
            matches = True
            match_text = note.title or note.filename

        if matches:
            # Prefer title as the inserted text
            insert_text = note.title if note.title else note.filename

            # Add notebook prefix if different from current
            if note.notebook != current_notebook:
                insert_text = f"{note.notebook}:{insert_text}"

            label = note.title if note.title else note.filename
            detail = f"[{note.id}] {note.filename}"
            if note.notebook != current_notebook:
                detail = f"{note.notebook}: {detail}"

            items.append(
                lsp.CompletionItem(
                    label=label,
                    kind=lsp.CompletionItemKind.Reference,
                    detail=detail,
                    insert_text=insert_text,
                    sort_text=f"{'0' if note.notebook == current_notebook else '1'}{label}",
                )
            )

    return items


def get_tag_completions(
    server: NbLanguageServer, partial: str
) -> list[lsp.CompletionItem]:
    """Get completion items for tags."""
    items = []
    tags = server.nb.get_tags()

    partial_lower = partial.lower()

    for tag in tags:
        if not partial or partial_lower in tag.lower():
            items.append(
                lsp.CompletionItem(
                    label=f"#{tag}",
                    kind=lsp.CompletionItemKind.Keyword,
                    detail="Tag",
                    # Insert just the tag name since # is already there
                    insert_text=tag,
                )
            )

    return items


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
@server.thread()
def definition(params: lsp.DefinitionParams) -> lsp.Location | None:
    """Go to definition for wiki-style links."""
    if server._shutting_down:
        return None
    document = server.workspace.get_text_document(params.text_document.uri)
    offset = position_to_offset(document, params.position)

    link = get_link_at_position(document.source, offset)
    if not link:
        return None

    # Determine notebook context
    current_notebook = server.get_notebook_for_uri(params.text_document.uri)
    notebook = link.notebook or current_notebook

    if not notebook:
        return None

    # Resolve the selector
    full_selector = f"{notebook}:{link.selector}" if notebook else link.selector
    path = server.nb.resolve_selector(full_selector)

    if path and path.exists():
        return lsp.Location(
            uri=path_to_uri(path),
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
        )

    return None


@server.feature(lsp.TEXT_DOCUMENT_DIAGNOSTIC)
@server.thread()
def diagnostics(params: lsp.DocumentDiagnosticParams) -> lsp.DocumentDiagnosticReport:
    """Provide diagnostics for broken wiki links."""
    if server._shutting_down:
        return lsp.RelatedFullDocumentDiagnosticReport(
            kind=lsp.DocumentDiagnosticReportKind.Full,
            items=[],
        )
    document = server.workspace.get_text_document(params.text_document.uri)
    current_notebook = server.get_notebook_for_uri(params.text_document.uri)

    diags: list[lsp.Diagnostic] = []

    # Check all wiki links
    for link in parse_wiki_links(document.source):
        notebook = link.notebook or current_notebook

        if not notebook:
            # Can't validate without knowing the notebook
            continue

        # Try to resolve
        full_selector = f"{notebook}:{link.selector}"
        path = server.nb.resolve_selector(full_selector)

        if path is None or not path.exists():
            start_pos = offset_to_position(document, link.start)
            end_pos = offset_to_position(document, link.end)

            diags.append(
                lsp.Diagnostic(
                    range=lsp.Range(start=start_pos, end=end_pos),
                    severity=lsp.DiagnosticSeverity.Error,
                    source="nb-lsp",
                    message=f"Broken link: '{link.full_selector}' not found",
                )
            )

    return lsp.RelatedFullDocumentDiagnosticReport(
        kind=lsp.DocumentDiagnosticReportKind.Full,
        items=diags,
    )


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams):
    """Handle document save - invalidate cache."""
    notebook = server.get_notebook_for_uri(params.text_document.uri)
    if notebook:
        server.nb.invalidate_cache(notebook)


@server.feature(lsp.SHUTDOWN)
def shutdown(params: None) -> None:
    """Handle shutdown request - terminate any running subprocesses."""
    logger.info("Shutting down nb-lsp")
    server._shutting_down = True
    server.nb.shutdown()


def main():
    """Run the LSP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    server.start_io()


if __name__ == "__main__":
    main()
