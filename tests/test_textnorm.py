from decimal import Decimal

from factpage.textnorm import norm, numbers, number_spans, proper_nouns, registrable_domain, years


def test_crore_rupees_canonical():
    assert numbers("₹1,200 crore") == {(Decimal("12000000000"), "₹")}


def test_rupee_spellings_match():
    assert numbers("Rs 1,200 crore") == numbers("INR 1200 crore") == numbers("Rs. 1,200 cr")


def test_billion_equals_million_form():
    assert numbers("$1.2 billion") == numbers("US$1,200 million")


def test_one_digit_difference_differs():
    assert numbers("$1.2 billion") != numbers("$1.3 billion")
    assert numbers("₹550 crore") != numbers("₹560 crore")


def test_percent():
    assert numbers("12.5%") == {(Decimal("12.5"), "%")}
    assert numbers("12.5 per cent") == numbers("12.5 percent") == numbers("12.5%")


def test_years_are_numbers_and_years():
    assert years("as of 2025, revenue rose") == {2025}
    assert (Decimal("2025"), "") in numbers("as of 2025")


def test_number_spans_as_written():
    assert number_spans("It cost ₹550 crore in 2024") == ["₹550 crore", "2024"]


def test_proper_nouns_exclude_stopwords():
    nouns = proper_nouns("The deal: Netflix paid Sony for rights")
    assert {"netflix", "sony"} <= nouns
    assert "the" not in nouns


def test_norm_unifies_quotes_and_dashes():
    assert norm("“Hello”—world") == norm('"hello" - world')


def test_registrable_domain_merges_subdomains():
    assert registrable_domain("https://en.m.wikipedia.org/wiki/X") == "wikipedia.org"
    assert registrable_domain("https://www.bbc.co.uk/news") == "bbc.co.uk"
