from __future__ import annotations

import json

from .models import OntologyProperty


PROFILE_NAME = "enterprise-documents"
PROFILE_VERSION = "2026-10-01"


# Descriptions are sent to extraction as rdfs:comment rows. The service has no
# preferred/fallback flag, so the fallback rule for mentions/about lives in the text.
_DESCRIPTIONS = {
    "worksFor": "Organizations that the person works for.",
    "memberOf": "An organization (such as a team or group) that the person is a member of.",
    "member": "A person who is a member of this project, including its lead.",
    "knows": "The most generic bi-directional social or work relation between two people.",
    "parentOrganization": "The larger organization that this organization is part of.",
    "sponsor": ("An organization that supports this project through a pledge, promise, "
                "or financial contribution."),
    "funder": "An organization that provides money for this project.",
    "attendee": "A person attending the event.",
    "organizer": "An organization that organizes the event.",
    "location": "The place where the organization is located.",
    "manufacturer": "The organization that makes the product.",
    "owns": "Products owned by the organization.",
    "provider": "The organization that provides the service or software.",
    "author": "The person who wrote this document.",
    "containedInPlace": "A place that contains this place.",
    "about": ("The project or system this document or event is about. Fallback: use only "
              "when no more specific relationship in this schema fits."),
    "mentions": ("An organization this document mentions. Fallback: use only when no more "
                 "specific relationship in this schema fits."),
}

# Consume issues one Search query per label per hop, so every label here costs
# round trips; keep this list short.
_RELATIONS = (
    ("Person", "worksFor", "Organization"),
    ("Person", "memberOf", "Organization"),
    ("Person", "knows", "Person"),
    ("Project", "member", "Person"),
    ("Organization", "parentOrganization", "Organization"),
    ("Project", "sponsor", "Organization"),
    ("Project", "funder", "Organization"),
    ("Event", "attendee", "Person"),
    ("Event", "organizer", "Organization"),
    ("Event", "about", "Project"),
    ("Event", "about", "SoftwareApplication"),
    ("Organization", "location", "Place"),
    ("Product", "manufacturer", "Organization"),
    ("Organization", "owns", "Product"),
    ("Service", "provider", "Organization"),
    ("SoftwareApplication", "provider", "Organization"),
    ("CreativeWork", "author", "Person"),
    ("CreativeWork", "about", "Project"),
    ("CreativeWork", "mentions", "Organization"),
    ("Place", "containedInPlace", "Place"),
)

_LITERALS = (
    ("name", "Thing", "Text", "The name of the item."),
    ("description", "Thing", "Text", "A description of the item."),
    ("url", "Thing", "URL", "URL of the item."),
    ("identifier", "Thing", "Text", "An identifier such as a ticket, product, or employee ID."),
    ("email", "Person", "Text", "Email address."),
    ("jobTitle", "Person", "Text", "The job title of the person."),
    ("legalName", "Organization", "Text", "The official name of the organization."),
    ("foundingDate", "Organization", "Date", "The date the organization was founded."),
    ("startDate", "Event", "DateTime", "The start date and time of the event."),
    ("endDate", "Event", "DateTime", "The end date and time of the event."),
)

PROFILE = {
    "name": PROFILE_NAME,
    "version": PROFILE_VERSION,
    "source": "https://schema.org/",
    "classes": {
        "Person": "A person, such as an employee, contact, or project lead.",
        "Organization": ("An organization such as a company, customer, vendor, team, "
                         "or department."),
        "Project": "An enterprise of a temporary nature, such as a program or initiative.",
        "Event": "Something that happens at a time and place, such as an incident or meeting.",
        "Product": "A product that is made or sold.",
        "SoftwareApplication": "A software application, platform, or system.",
        "Service": "A service provided by an organization.",
        "CreativeWork": "A document such as a report, policy, specification, or record.",
        "Place": "A physical place such as a site, city, or region.",
    },
    "properties": [
        *({"name": name, "domain": domain, "range": range_name, "value_kind": "literal",
           "description": text} for name, domain, range_name, text in _LITERALS),
        *({"name": name, "domain": domain, "range": range_name, "value_kind": "entity",
           "description": _DESCRIPTIONS[name]} for domain, name, range_name in _RELATIONS),
    ],
}

PROFILES = {PROFILE_VERSION: PROFILE}


def canonical_profile_bytes(version: str = PROFILE_VERSION) -> bytes:
    return json.dumps(PROFILES[version], sort_keys=True, separators=(",", ":")).encode("utf-8")


def profile_properties(version: str = PROFILE_VERSION) -> tuple[OntologyProperty, ...]:
    return tuple(OntologyProperty(**item) for item in PROFILES[version]["properties"])
