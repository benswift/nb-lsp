"""Parsing and handling of nb selectors and wiki-style links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class LinkType(Enum):
    """Type of wiki-style link."""

    TITLE = auto()      # [[My Note Title]]
    ID = auto()         # [[123]]
    FILENAME = auto()   # [[note.md]]
    PATH = auto()       # [[folder/note.md]] or [[folder/123]]


@dataclass
class WikiLink:
    """A parsed wiki-style link."""

    notebook: str | None   # None means current notebook
    selector: str          # The id, filename, title, or path
    display_text: str | None  # Text after | if present
    link_type: LinkType
    start: int            # Start position in document
    end: int              # End position in document

    @property
    def full_selector(self) -> str:
        """Return the full selector including notebook if present."""
        if self.notebook:
            return f"{self.notebook}:{self.selector}"
        return self.selector


# Pattern for wiki-style links: [[selector]] or [[selector|display text]]
# Selector can be: notebook:path or just path
# Path can be: id, filename, title, or folder/path
WIKI_LINK_PATTERN = re.compile(
    r"\[\["
    r"(?:([a-zA-Z0-9_-]+):)?"  # Optional notebook name with colon
    r"([^\]|]+)"               # Selector (required)
    r"(?:\|([^\]]+))?"         # Optional display text after |
    r"\]\]"
)

# Pattern for tags
TAG_PATTERN = re.compile(r"(?<![a-zA-Z0-9])#([a-zA-Z0-9_/-]+)")


def classify_selector(selector: str) -> LinkType:
    """Classify what type of selector this is."""
    # Contains a slash -> it's a path
    if "/" in selector:
        return LinkType.PATH

    # Pure digits -> ID
    if selector.isdigit():
        return LinkType.ID

    # Has a file extension -> filename
    if "." in selector and not selector.startswith("."):
        return LinkType.FILENAME

    # Otherwise assume it's a title
    return LinkType.TITLE


def parse_wiki_links(text: str) -> list[WikiLink]:
    """Parse all wiki-style links from text."""
    links = []

    for match in WIKI_LINK_PATTERN.finditer(text):
        notebook = match.group(1)
        selector = match.group(2).strip()
        display_text = match.group(3)

        if display_text:
            display_text = display_text.strip()

        link_type = classify_selector(selector)

        links.append(WikiLink(
            notebook=notebook,
            selector=selector,
            display_text=display_text,
            link_type=link_type,
            start=match.start(),
            end=match.end(),
        ))

    return links


def parse_tags(text: str) -> list[tuple[str, int, int]]:
    """Parse all tags from text.

    Returns:
        List of (tag_name, start_pos, end_pos) tuples.
        tag_name does not include the # prefix.
    """
    tags = []

    for match in TAG_PATTERN.finditer(text):
        tag = match.group(1)
        tags.append((tag, match.start(), match.end()))

    return tags


def get_link_at_position(text: str, position: int) -> WikiLink | None:
    """Get the wiki link at the given position, if any."""
    for link in parse_wiki_links(text):
        if link.start <= position <= link.end:
            return link
    return None


def get_tag_at_position(text: str, position: int) -> tuple[str, int, int] | None:
    """Get the tag at the given position, if any."""
    for tag, start, end in parse_tags(text):
        if start <= position <= end:
            return (tag, start, end)
    return None


def is_inside_link_brackets(text: str, position: int) -> bool:
    """Check if position is inside [[ ]] brackets (for completion trigger)."""
    # Look backwards for [[
    before = text[:position]
    after = text[position:]

    # Find last [[ before position
    last_open = before.rfind("[[")
    if last_open == -1:
        return False

    # Check no ]] between [[ and position
    between = before[last_open:]
    if "]]" in between:
        return False

    # We're inside brackets - could be complete or incomplete
    return True


def is_inside_tag(text: str, position: int) -> bool:
    """Check if position is right after a # (for tag completion trigger)."""
    if position == 0:
        return False

    # Look for # immediately before or within current word
    before = text[:position]

    # Find start of current word
    word_start = position
    while word_start > 0 and (before[word_start - 1].isalnum() or before[word_start - 1] in "_-/#"):
        word_start -= 1

    # Check if word starts with #
    if word_start < len(before) and before[word_start] == "#":
        # Make sure it's not preceded by another alphanumeric (e.g., "test#tag")
        if word_start == 0 or not before[word_start - 1].isalnum():
            return True

    return False


def get_partial_link_content(text: str, position: int) -> str | None:
    """Get the partial content inside [[ ]] at position for completion."""
    if not is_inside_link_brackets(text, position):
        return None

    before = text[:position]
    last_open = before.rfind("[[")

    # Extract content between [[ and cursor
    content = before[last_open + 2:]

    # If there's a | for display text, only return selector part
    if "|" in content:
        return None  # Don't complete in display text area

    return content


def get_partial_tag(text: str, position: int) -> str | None:
    """Get the partial tag at position for completion."""
    if not is_inside_tag(text, position):
        return None

    before = text[:position]

    # Find the #
    word_start = position
    while word_start > 0 and (before[word_start - 1].isalnum() or before[word_start - 1] in "_-/#"):
        word_start -= 1

    if word_start >= len(before) or before[word_start] != "#":
        return None

    # Return content after #
    return before[word_start + 1:]
