"""Name normalisation and company domains (the Python normaliser replaced the SQL one in migration 0002)."""

from __future__ import annotations

import pytest

from projectzero.dealflow.identity import company_domain, is_placeholder_name, normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ölwerk Süd GmbH", "ölwerk süd"),  # accents kept (the old SQL turned this into "lwerk s d")
        ("Acme Robotics GmbH & Co. KG", "acme robotics"),  # stacked legal forms stripped from the end
        ("Co Robotics", "co robotics"),  # a legal token at the start is part of the name
        ("Nordic Wind A/S", "nordic wind"),
        ("株式会社テックラボ", "株式会社テックラボ"),  # unspaced scripts survive (old SQL: NULL)
        ("王小明", "王小明"),
        ("  MIMIC  robotics  AG ", "mimic robotics"),
        ("ＡＣＭＥ Robotics", "acme robotics"),  # NFKC folds full-width letters
        ("Straße Labs", "strasse labs"),  # casefold
        ("AG", "ag"),  # never strip the only token
        ("", None),
        ("---", None),
    ],
)
def test_normalize_name(raw: str, expected: str | None) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("name", ["UNKNOWN", "unknown", "N/A", "", "  ", "Stealth", None])
def test_placeholder_names(name: str | None) -> None:
    assert is_placeholder_name(name)


def test_real_names_are_not_placeholders() -> None:
    assert not is_placeholder_name("Freda")
    assert not is_placeholder_name("Stealth Robotics GmbH")


@pytest.mark.parametrize(
    ("website", "domain"),
    [
        ("https://aereus.de", "aereus.de"),
        ("https://www.app.aereus.de/careers?x=1", "aereus.de"),
        ("aereus.de", "aereus.de"),
        ("https://shop.example.co.uk/", "example.co.uk"),
        ("https://acme.github.io", None),
        ("https://linktr.ee/acme", None),
        ("https://www.linkedin.com/company/acme", None),
        ("https://mavt.ethz.ch/news/acme", None),
        ("https://robotics.stanford.edu/acme", None),
        ("https://www.cs.ox.ac.uk/acme", None),
        ("UNKNOWN", None),
        ("", None),
        (None, None),
        ("https://exa mple.com", None),
    ],
)
def test_company_domain(website: str | None, domain: str | None) -> None:
    assert company_domain(website) == domain
