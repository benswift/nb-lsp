"""Tests for the selectors module."""

import pytest

from nb_lsp.selectors import (
    LinkType,
    WikiLink,
    classify_selector,
    get_link_at_position,
    get_partial_link_content,
    get_partial_tag,
    get_tag_at_position,
    is_inside_link_brackets,
    is_inside_tag,
    parse_tags,
    parse_wiki_links,
)


class TestClassifySelector:
    """Tests for classify_selector function."""

    def test_numeric_id(self):
        assert classify_selector("123") == LinkType.ID
        assert classify_selector("1") == LinkType.ID
        assert classify_selector("999999") == LinkType.ID

    def test_filename(self):
        assert classify_selector("note.md") == LinkType.FILENAME
        assert classify_selector("example.txt") == LinkType.FILENAME
        assert classify_selector("my-note.org") == LinkType.FILENAME

    def test_path(self):
        assert classify_selector("folder/note.md") == LinkType.PATH
        assert classify_selector("folder/123") == LinkType.PATH
        assert classify_selector("a/b/c/note") == LinkType.PATH

    def test_title(self):
        assert classify_selector("My Note Title") == LinkType.TITLE
        assert classify_selector("Example") == LinkType.TITLE
        assert classify_selector("Notes about Python") == LinkType.TITLE


class TestParseWikiLinks:
    """Tests for parse_wiki_links function."""

    def test_simple_link(self):
        text = "Check out [[My Note]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].selector == "My Note"
        assert links[0].notebook is None
        assert links[0].display_text is None
        assert links[0].link_type == LinkType.TITLE

    def test_link_with_id(self):
        text = "See [[123]] for details."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].selector == "123"
        assert links[0].link_type == LinkType.ID

    def test_link_with_filename(self):
        text = "Check [[notes.md]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].selector == "notes.md"
        assert links[0].link_type == LinkType.FILENAME

    def test_link_with_notebook(self):
        text = "See [[work:Meeting Notes]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].notebook == "work"
        assert links[0].selector == "Meeting Notes"
        assert links[0].link_type == LinkType.TITLE

    def test_link_with_notebook_and_id(self):
        text = "Check [[personal:42]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].notebook == "personal"
        assert links[0].selector == "42"
        assert links[0].link_type == LinkType.ID

    def test_link_with_display_text(self):
        text = "See [[123|my custom text]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].selector == "123"
        assert links[0].display_text == "my custom text"

    def test_link_with_notebook_and_display_text(self):
        text = "Check [[work:Project Plan|the plan]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].notebook == "work"
        assert links[0].selector == "Project Plan"
        assert links[0].display_text == "the plan"

    def test_link_with_path(self):
        text = "See [[folder/subfolder/note.md]]."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].selector == "folder/subfolder/note.md"
        assert links[0].link_type == LinkType.PATH

    def test_multiple_links(self):
        text = "See [[First Note]] and [[Second Note]] and [[work:Third]]."
        links = parse_wiki_links(text)

        assert len(links) == 3
        assert links[0].selector == "First Note"
        assert links[1].selector == "Second Note"
        assert links[2].notebook == "work"
        assert links[2].selector == "Third"

    def test_link_positions(self):
        text = "Start [[Link]] end."
        links = parse_wiki_links(text)

        assert len(links) == 1
        assert links[0].start == 6
        assert links[0].end == 14
        assert text[links[0].start : links[0].end] == "[[Link]]"

    def test_no_links(self):
        text = "No links here. Just [single brackets] or plain text."
        links = parse_wiki_links(text)

        assert len(links) == 0

    def test_full_selector_property(self):
        text = "[[work:Note]] and [[Local Note]]"
        links = parse_wiki_links(text)

        assert links[0].full_selector == "work:Note"
        assert links[1].full_selector == "Local Note"


class TestParseTags:
    """Tests for parse_tags function."""

    def test_simple_tag(self):
        text = "This has #tag1 in it."
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][0] == "tag1"

    def test_multiple_tags(self):
        text = "#tag1 #tag2 #tag3"
        tags = parse_tags(text)

        assert len(tags) == 3
        assert [t[0] for t in tags] == ["tag1", "tag2", "tag3"]

    def test_nested_tag(self):
        text = "Check #project/design/ui for info."
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][0] == "project/design/ui"

    def test_tag_with_dashes(self):
        text = "Use #my-tag-here."
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][0] == "my-tag-here"

    def test_tag_with_underscores(self):
        text = "Use #my_tag_here."
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][0] == "my_tag_here"

    def test_tag_positions(self):
        text = "Text #mytag more."
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][1] == 5  # start
        assert tags[0][2] == 11  # end
        assert text[tags[0][1] : tags[0][2]] == "#mytag"

    def test_no_tags(self):
        text = "No tags here, just some text."
        tags = parse_tags(text)

        assert len(tags) == 0

    def test_tag_at_start(self):
        text = "#first and more"
        tags = parse_tags(text)

        assert len(tags) == 1
        assert tags[0][0] == "first"

    def test_not_tag_in_word(self):
        text = "test#not a tag"
        tags = parse_tags(text)

        # Should not match # preceded by alphanumeric
        assert len(tags) == 0


class TestGetLinkAtPosition:
    """Tests for get_link_at_position function."""

    def test_position_inside_link(self):
        text = "See [[My Link]] here."
        link = get_link_at_position(text, 8)  # Inside "My Link"

        assert link is not None
        assert link.selector == "My Link"

    def test_position_at_brackets(self):
        text = "See [[My Link]] here."
        link = get_link_at_position(text, 4)  # At first [

        assert link is not None
        assert link.selector == "My Link"

    def test_position_outside_link(self):
        text = "See [[My Link]] here."
        link = get_link_at_position(text, 18)  # At "here"

        assert link is None

    def test_position_between_links(self):
        text = "[[First]] middle [[Second]]"
        link = get_link_at_position(text, 12)  # At "middle"

        assert link is None


class TestGetTagAtPosition:
    """Tests for get_tag_at_position function."""

    def test_position_inside_tag(self):
        text = "Text #mytag here."
        tag = get_tag_at_position(text, 8)  # Inside "mytag"

        assert tag is not None
        assert tag[0] == "mytag"

    def test_position_outside_tag(self):
        text = "Text #mytag here."
        tag = get_tag_at_position(text, 14)  # At "here"

        assert tag is None


class TestIsInsideLinkBrackets:
    """Tests for is_inside_link_brackets function."""

    def test_inside_empty_brackets(self):
        text = "Text [["
        assert is_inside_link_brackets(text, 7) is True

    def test_inside_partial_content(self):
        text = "Text [[My No"
        assert is_inside_link_brackets(text, 12) is True

    def test_inside_complete_link(self):
        text = "Text [[My Note]]"
        assert is_inside_link_brackets(text, 10) is True

    def test_after_closed_brackets(self):
        text = "Text [[Note]] more"
        assert is_inside_link_brackets(text, 16) is False

    def test_outside_brackets(self):
        text = "No brackets here"
        assert is_inside_link_brackets(text, 5) is False

    def test_single_bracket(self):
        text = "Text [single"
        assert is_inside_link_brackets(text, 8) is False


class TestIsInsideTag:
    """Tests for is_inside_tag function."""

    def test_right_after_hash(self):
        text = "Text #"
        assert is_inside_tag(text, 6) is True

    def test_inside_tag_word(self):
        text = "Text #my"
        assert is_inside_tag(text, 8) is True

    def test_before_hash(self):
        text = "Text #tag"
        assert is_inside_tag(text, 4) is False

    def test_no_hash(self):
        text = "No tag here"
        assert is_inside_tag(text, 5) is False


class TestGetPartialLinkContent:
    """Tests for get_partial_link_content function."""

    def test_empty_brackets(self):
        text = "Text [["
        assert get_partial_link_content(text, 7) == ""

    def test_partial_content(self):
        text = "Text [[My No"
        assert get_partial_link_content(text, 12) == "My No"

    def test_with_notebook_prefix(self):
        text = "Text [[work:Mee"
        assert get_partial_link_content(text, 15) == "work:Mee"

    def test_outside_brackets(self):
        text = "No brackets"
        assert get_partial_link_content(text, 5) is None

    def test_inside_display_text(self):
        text = "Text [[Note|disp"
        assert get_partial_link_content(text, 16) is None  # Don't complete in display area


class TestGetPartialTag:
    """Tests for get_partial_tag function."""

    def test_right_after_hash(self):
        text = "Text #"
        assert get_partial_tag(text, 6) == ""

    def test_partial_tag(self):
        text = "Text #my"
        assert get_partial_tag(text, 8) == "my"

    def test_outside_tag(self):
        text = "No tag"
        assert get_partial_tag(text, 3) is None
