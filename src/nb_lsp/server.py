"""LSP server for nb note-taking tool."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument

from .nb import NbClient, Note
from .selectors import (
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

    async def get_notebook_for_uri(self, uri: str) -> str | None:
        """Get the notebook name for a document URI."""
        path = uri_to_path(uri)
        if path:
            return await self.nb.get_current_notebook(path)
        return None

    async def get_all_notes(self) -> list[Note]:
        """Get all notes from all notebooks."""
        notes = []
        for notebook in await self.nb.get_notebooks():
            notes.extend(await self.nb.get_notes(notebook.name))
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
        line_len = len(line) + 1
        if current + line_len > offset:
            return lsp.Position(line=line_num, character=offset - current)
        current += line_len
    return lsp.Position(line=len(lines) - 1, character=len(lines[-1]))


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
async def completions(params: lsp.CompletionParams) -> lsp.CompletionList | None:
    """Provide completions for wiki-style links and tags."""
    if server._shutting_down:
        return None

    document = server.workspace.get_text_document(params.text_document.uri)
    offset = position_to_offset(document, params.position)
    text = document.source

    items: list[lsp.CompletionItem] = []

    if is_inside_link_brackets(text, offset):
        partial = get_partial_link_content(text, offset) or ""
        items = await get_link_completions(server, params.text_document.uri, partial)
    elif is_inside_tag(text, offset):
        partial = get_partial_tag(text, offset) or ""
        items = await get_tag_completions(server, partial)

    if items:
        return lsp.CompletionList(is_incomplete=False, items=items)

    return None


async def get_link_completions(
    server: NbLanguageServer, uri: str, partial: str
) -> list[lsp.CompletionItem]:
    """Get completion items for wiki links."""
    items = []
    current_notebook = await server.get_notebook_for_uri(uri)

    notebook_filter = None
    selector_partial = partial

    if ":" in partial:
        notebook_filter, selector_partial = partial.split(":", 1)

    notebooks = await server.nb.get_notebooks()

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

    notes_to_show = []

    if notebook_filter:
        matching_notebooks = [nb for nb in notebooks if nb.name == notebook_filter]
        for nb in matching_notebooks:
            notes_to_show.extend(await server.nb.get_notes(nb.name))
    else:
        notes_to_show = await server.get_all_notes()

    selector_lower = selector_partial.lower()

    for note in notes_to_show:
        matches = False

        if note.title and selector_lower in note.title.lower():
            matches = True
        elif selector_lower in note.filename.lower():
            matches = True
        elif selector_lower in note.id:
            matches = True

        if not selector_partial:
            matches = True

        if matches:
            insert_text = note.title if note.title else note.filename

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


async def get_tag_completions(
    server: NbLanguageServer, partial: str
) -> list[lsp.CompletionItem]:
    """Get completion items for tags."""
    items = []
    tags = await server.nb.get_tags()

    partial_lower = partial.lower()

    for tag in tags:
        if not partial or partial_lower in tag.lower():
            items.append(
                lsp.CompletionItem(
                    label=f"#{tag}",
                    kind=lsp.CompletionItemKind.Keyword,
                    detail="Tag",
                    insert_text=tag,
                )
            )

    return items


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
async def definition(params: lsp.DefinitionParams) -> lsp.Location | None:
    """Go to definition for wiki-style links."""
    if server._shutting_down:
        return None

    document = server.workspace.get_text_document(params.text_document.uri)
    offset = position_to_offset(document, params.position)

    link = get_link_at_position(document.source, offset)
    if not link:
        return None

    current_notebook = await server.get_notebook_for_uri(params.text_document.uri)
    notebook = link.notebook or current_notebook

    if not notebook:
        return None

    full_selector = f"{notebook}:{link.selector}" if notebook else link.selector
    path = await server.nb.resolve_selector(full_selector)

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
async def diagnostics(
    params: lsp.DocumentDiagnosticParams,
) -> lsp.DocumentDiagnosticReport:
    """Provide diagnostics for broken wiki links."""
    if server._shutting_down:
        return lsp.RelatedFullDocumentDiagnosticReport(
            kind=lsp.DocumentDiagnosticReportKind.Full,
            items=[],
        )

    document = server.workspace.get_text_document(params.text_document.uri)
    current_notebook = await server.get_notebook_for_uri(params.text_document.uri)

    diags: list[lsp.Diagnostic] = []

    for link in parse_wiki_links(document.source):
        notebook = link.notebook or current_notebook

        if not notebook:
            continue

        full_selector = f"{notebook}:{link.selector}"
        path = await server.nb.resolve_selector(full_selector)

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
async def did_save(params: lsp.DidSaveTextDocumentParams):
    """Handle document save - invalidate cache."""
    notebook = await server.get_notebook_for_uri(params.text_document.uri)
    if notebook:
        server.nb.invalidate_cache(notebook)


@server.feature(lsp.SHUTDOWN)
def shutdown(params: None) -> None:
    """Handle shutdown request."""
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
