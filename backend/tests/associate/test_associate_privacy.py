"""Codex H-317: the searchable help agrees with the page about where the data lives. The documents stay byte-identical;
their local-data claims are corrected at index time, so no indexed passage (and no offline answer) says the data stays
on the machine: conversations and records are saved in the Project Zero database."""

from __future__ import annotations

from projectzero.associate import knowledge


def _indexed() -> str:
    return "\n".join(s.text for s in knowledge.index()["sections"])


def test_no_indexed_passage_claims_the_data_stays_local() -> None:
    assert knowledge.LOCAL_CLAIM.findall(_indexed()) == []


def test_every_local_claim_in_the_raw_documents_is_corrected_not_dropped() -> None:
    raw = "\n".join((knowledge.docs_dir() / rel).read_text(encoding="utf-8") for rel, _ in knowledge.DOCS)
    claims = [m.group(0) for m in knowledge.LOCAL_CLAIM.finditer(raw)]
    assert claims  # the documents do make the claim (the test would be vacuous otherwise)
    assert _indexed().count("Project Zero database") >= len([c for c in claims if "machine" not in c])


def test_the_corrections_say_where_the_data_lives() -> None:
    assert knowledge.corrected("Map tiles come from CDNs; all data stays local.") == (
        "Map tiles come from CDNs; all data is saved in the Project Zero database."
    )
    assert knowledge.corrected("Conversations are kept locally, at most 60") == (
        "Conversations are saved in the Project Zero database, at most 60"
    )
    assert knowledge.corrected("Taste Map · data stays local") == "Taste Map · data in your Project Zero database"
