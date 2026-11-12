"""The old ``domain/founder_radar/csv_import.py`` (rev 6c739b9), ported line for line (review 026a): an authorized
import — the official LinkedIn Connections export or a custom CSV (nothing is scraped). Only change: the clock
(``now``, the Berlin wall clock) stamps ``import_date`` / ``retrieved``."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any

from projectzero.founder_radar.names import canonical_linkedin, is_person_name


def parse_import_csv(
    text: Any, include_email: bool = False, label: Any = "CSV", *, now: datetime
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Custom format (name, linkedin, company, role, location, country) OR the official LinkedIn Connections export
    (First Name, Last Name, URL, Email Address, Company, Position, Connected On). Handles BOM, LinkedIn's preamble
    lines, header capitalization and TSV. Returns (candidates, skipped_rows, format)."""
    raw = str(text or "").lstrip("﻿")
    lines = raw.splitlines()
    hdr = next(
        (
            i
            for i, ln in enumerate(lines)
            if re.search(r"\bfirst name\b", ln, re.I) and re.search(r"\blast name\b", ln, re.I)
        ),
        None,
    )
    if hdr is None:
        hdr = next(
            (i for i, ln in enumerate(lines) if re.search(r"\bname\b", ln, re.I) and ("," in ln or "\t" in ln)), 0
        )
    body = "\n".join(lines[hdr:])
    delim = "\t" if body.count("\t") > body.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(body), delimiter=delim))

    def norm(r: dict[Any, Any]) -> dict[str, str]:
        return {re.sub(r"\s+", " ", (k or "")).strip().lower(): (v or "").strip() for k, v in r.items()}

    fmt = (
        "linkedin_connections"
        if hdr is not None and any("first name" in (k or "").lower() for k in (rows[0].keys() if rows else []))
        else "custom"
    )
    today = now.strftime("%Y-%m-%d %H:%M")
    out, skipped = [], []
    for r in rows:
        n = norm(r)
        if fmt == "linkedin_connections":
            nm = (n.get("first name", "") + " " + n.get("last name", "")).strip()
            url = canonical_linkedin(n.get("url", ""))
            company = n.get("company", "")
            role = n.get("position", "")
            connected = n.get("connected on", "")
            email = n.get("email address", "") if include_email else ""
            location = ""
            country = ""
        else:
            nm = n.get("name", "")
            url = canonical_linkedin(n.get("linkedin", ""))
            company = n.get("company", "")
            role = n.get("role", "")
            connected = ""
            email = n.get("email", "") if include_email else ""
            location = n.get("location", "")
            country = n.get("country", "")
        if not is_person_name(nm):
            if nm:
                skipped.append(nm)
            continue
        c: dict[str, Any] = {
            "name": nm,
            "company": company,
            "role": role,
            "location": location,
            "country": country,
            "linkedin": url,
            "profile_urls": [url] if url else [],
            "evidence": [],
            "why_surfaced": f"authorized import ({label})",
            "import_label": label,
            "import_date": today,
            "sources": [
                {
                    "source": "Authorized import — " + label,
                    "source_id": "import",
                    "url": url,
                    "retrieved": today,
                    "route": "manual",
                    "by": "operator",
                }
            ],
        }
        if email:
            c["email"] = email
        if fmt == "linkedin_connections":
            c.update(
                {
                    "provenance_label": "authorized LinkedIn Connections export",
                    "linkedin_connection_degree": 1,
                    "connection_source": "linkedin_export",
                    "linkedin_connected_on": connected,
                }
            )
        out.append(c)
    return out, skipped, fmt
