"""Unit tests for the ranking parser — no network required."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import parse_ranking, aggregate_rankings


REVIEW_1 = """
Response A was sharp on the riskiest assumption but weak on unit economics.
Response B gave generic advice.
Response C had the best cheapest test.

FINAL RANKING:
1. Response C
2. Response A
3. Response B
"""

REVIEW_2 = """
Response B actually had a great kill criterion.
Response A was verbose.
Response C missed the competition.

FINAL RANKING:
1. Response B
2. Response C
3. Response A
"""

REVIEW_MISSING_BLOCK = """
I think Response A was the best overall, followed by B and C.
No explicit ranking block here.
"""


def test_parse_ranking_basic():
    letters = ["A", "B", "C"]
    r = parse_ranking(REVIEW_1, letters)
    assert r["C"] == 1
    assert r["A"] == 2
    assert r["B"] == 3


def test_parse_ranking_second():
    letters = ["A", "B", "C"]
    r = parse_ranking(REVIEW_2, letters)
    assert r["B"] == 1
    assert r["C"] == 2
    assert r["A"] == 3


def test_parse_ranking_fallback():
    letters = ["A", "B", "C"]
    r = parse_ranking(REVIEW_MISSING_BLOCK, letters)
    # fallback: alphabetical order 1,2,3
    assert r["A"] == 1
    assert r["B"] == 2
    assert r["C"] == 3


def test_aggregate_rankings():
    letters = ["A", "B", "C"]
    r1 = parse_ranking(REVIEW_1, letters)  # C=1, A=2, B=3
    r2 = parse_ranking(REVIEW_2, letters)  # B=1, C=2, A=3
    avg = aggregate_rankings([r1, r2], letters)
    # A: (2+3)/2 = 2.5
    # B: (3+1)/2 = 2.0
    # C: (1+2)/2 = 1.5
    assert avg["C"] == 1.5
    assert avg["B"] == 2.0
    assert avg["A"] == 2.5


def test_aggregate_rankings_single_reviewer():
    letters = ["A", "B"]
    r1 = {"A": 1, "B": 2}
    avg = aggregate_rankings([r1], letters)
    assert avg["A"] == 1.0
    assert avg["B"] == 2.0
