from tearsheet.output import estimate_tokens, slugify, truncate


class TestEstimateTokens:
    def test_four_chars_per_token(self) -> None:
        assert estimate_tokens("a" * 400) == 100

    def test_empty_is_zero(self) -> None:
        assert estimate_tokens("") == 0


class TestTruncate:
    def test_short_text_returned_unchanged(self) -> None:
        text, was_truncated = truncate("hello\nworld", 100)
        assert text == "hello\nworld"
        assert was_truncated is False

    def test_truncates_at_line_boundary(self) -> None:
        md = "# Title\n\n" + ("alpha bravo charlie\n" * 50)
        text, was_truncated = truncate(md, 200)
        assert was_truncated is True
        assert len(text) <= 200
        # never cuts mid-line: result must be a prefix of whole lines
        assert md.startswith(text)
        assert text.endswith("\n") or md[len(text)] == "\n"

    def test_zero_max_means_unlimited(self) -> None:
        md = "x" * 100_000
        text, was_truncated = truncate(md, 0)
        assert text == md
        assert was_truncated is False

    def test_single_huge_line_hard_cut(self) -> None:
        md = "y" * 5000
        text, was_truncated = truncate(md, 300)
        assert was_truncated is True
        assert len(text) == 300


class TestSlugify:
    def test_basic_title(self) -> None:
        assert slugify("How to Foo") == "how-to-foo"

    def test_strips_punctuation(self) -> None:
        assert slugify("What's New? (2026 Edition!)") == "whats-new-2026-edition"

    def test_empty_becomes_untitled(self) -> None:
        assert slugify("") == "untitled"
        assert slugify("???") == "untitled"

    def test_length_capped_at_word_boundary(self) -> None:
        slug = slugify("word " * 40, max_len=20)
        assert len(slug) <= 20
        assert not slug.endswith("-")
