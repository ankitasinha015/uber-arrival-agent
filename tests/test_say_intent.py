"""Free-text at a pause: direct restaurant/dish/ordinal selection and refinement.

The composer feeds /say → registry.say → either a direct pick (_match_option) or a
refine (parse_intent). These cover the matcher so 'the parlor pizza bar' picks it
instead of being read as a 'more pizza' refinement."""

from __future__ import annotations

from arrival_agent.web import concierge as C

_OPTS = [
    {"option_id": "opt-1", "restaurant_name": "RPM Steak", "items": ["BBQ Ribs"]},
    {"option_id": "opt-2", "restaurant_name": "Parlor Pizza Bar", "items": ["Margherita Pizza"]},
    {"option_id": "opt-3", "restaurant_name": "Pizzeria Portofino", "items": ["Marinara Slice"]},
]


def _pick(text):
    o = C._match_option(text, _OPTS)
    return o["option_id"] if o else None


def test_match_by_full_name_and_token():
    assert _pick("the parlor pizza bar") == "opt-2"
    assert _pick("portofino") == "opt-3"
    assert _pick("rpm") == "opt-1"          # 3-letter distinctive token


def test_match_by_dish_and_ordinal():
    assert _pick("margherita") == "opt-2"
    assert _pick("the ribs") == "opt-1"
    assert _pick("the first one") == "opt-1"
    assert _pick("number 3") == "opt-3"


def test_ambiguous_or_refinement_text_does_not_falsely_pick():
    # a bare cuisine or a refine phrase must fall through to parse_intent, not pick
    assert _pick("pizza") is None
    assert _pick("something cheaper") is None
    assert C.parse_intent("something cheaper", "pick")["decision"] == "refine"
    assert C.parse_intent("the pizza one", "pick")["mode"] == "cuisine"
