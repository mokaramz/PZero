"""The event source catalogue the Events page lists: the old ``domain/connectors.py`` ``EVENT_PAGES`` (:806-848) and
``MANUAL_EVENT_SOURCES`` (:850-891) (rev 6c739b9), VERBATIM. The scan that fetches ``EVENT_PAGES`` is review 017.
"""

from __future__ import annotations

EVENT_PAGES = [
    {"name": "Pioniergarage Karlsruhe", "url": "https://pioniergarage.de/", "city": "Karlsruhe", "type": "university"},
    {"name": "KIT events", "url": "https://www.kit.edu/kit/english/events.php", "city": "Karlsruhe", "type": "university"},
    {"name": "UnternehmerTUM events", "url": "https://www.unternehmertum.de/en/events", "city": "Munich",
     "type": "accelerator"},
    {"name": "ETH Entrepreneur Club", "url": "https://www.entrepreneur-club.org/", "city": "Zürich", "type": "university"},
    {"name": "EPFL innovation events", "url": "https://www.epfl.ch/innovation/", "city": "Lausanne",
     "type": "university"},
    {"name": "START Global (St. Gallen)", "url": "https://www.startglobal.org/", "city": "St. Gallen",
     "type": "founder_meetup"},
    {"name": "MLH 2026 season", "url": "https://mlh.io/seasons/2026/events", "city": "", "type": "hackathon"},
    {"name": "Google for Startups events", "url": "https://startup.google.com/events/", "city": "", "type": "corporate"},
    {"name": "AWS events", "url": "https://aws.amazon.com/events/", "city": "", "type": "corporate"},
    {"name": "NVIDIA events", "url": "https://www.nvidia.com/en-us/events/", "city": "", "type": "corporate"},
    {"name": "Bits & Pretzels", "url": "https://www.bitsandpretzels.com/", "city": "Munich", "type": "founder_meetup"},
]  # fmt: skip

MANUAL_EVENT_SOURCES = [
    {
        "name": "Meetup — search per city",
        "url": "https://www.meetup.com/find/?keywords=startup&location=de--Karlsruhe",
        "how": "Search 'startup', 'AI', 'robotics' per focus city. API is paid — manual weekly check.",
    },
    {
        "name": "Eventbrite — search per city",
        "url": "https://www.eventbrite.de/d/germany--karlsruhe/startup/",
        "how": "Same routine. Swap city in the URL.",
    },
    {
        "name": "LinkedIn Events",
        "url": "https://www.linkedin.com/search/results/events/?keywords=startup",
        "how": "Manual only (ToS). Log good finds via Add Event.",
    },
    {
        "name": "Gründerschmiede / KIT founder programs",
        "url": "https://www.gruenderschmiede.info/",
        "how": "Karlsruhe founder programs — check monthly.",
    },
    {
        "name": "Luma ICS calendars",
        "url": "https://lu.ma/discover",
        "how": "Best structured source: subscribe to a calendar, copy the .ics link into EVENT_ICS in connectors.py (instructions in the file).",
    },
    {
        "name": "Corporate: SAP / Siemens / Bosch / Porsche / Mercedes / BMW innovation events",
        "url": "https://events.sap.com/",
        "how": "Each runs its own calendar; check when planning a city trip.",
    },
    {
        "name": "Consulting: McKinsey / BCG / Bain / Big-4 innovation events",
        "url": "https://www.mckinsey.com/careers/events",
        "how": "Occasional but high-density rooms. Check quarterly per firm.",
    },
    {
        "name": "hessian.AI / TU Darmstadt events",
        "url": "https://hessian.ai/news-events/",
        "how": "Darmstadt AI ecosystem — your old ground.",
    },
]
