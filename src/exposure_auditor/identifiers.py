"""Normalization rules for the identifiers a user can put in scope."""

import re
import unicodedata
from datetime import date

from email_validator import EmailNotValidError, validate_email

VERIFIABLE_KINDS = frozenset({"email", "phone"})
# Context details are never search terms. They exist to tell the account
# holder apart from other people who share their name.
CONTEXT_KINDS = frozenset({"city", "birth_year", "workplace"})
ATTESTED_KINDS = frozenset({"name", "username", "image"}) | CONTEXT_KINDS
ALL_KINDS = VERIFIABLE_KINDS | ATTESTED_KINDS
CONTEXT_CAPS = {"city": 3, "birth_year": 1, "workplace": 3}

_PHONE = re.compile(r"^\+[1-9]\d{6,14}$")
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,40}$")


class InvalidIdentifier(ValueError):
    pass


def normalize(kind: str, value: str) -> str:
    v = unicodedata.normalize("NFC", value).strip()
    if kind == "email":
        try:
            return validate_email(v, check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise InvalidIdentifier(str(exc)) from exc
    if kind == "phone":
        v = re.sub(r"[\s\-().]", "", v)
        if not _PHONE.match(v):
            raise InvalidIdentifier("phone numbers must be in international format, e.g. +358401234567")
        return v
    if kind == "name":
        tokens = v.split()
        # A single token ("Maria") matches half the internet and would make
        # the scope guard meaningless, so require at least a first and last name.
        if len(tokens) < 2 or len(v) > 100:
            raise InvalidIdentifier("give a full name (at least first and last name, max 100 characters)")
        return " ".join(tokens)
    if kind == "username":
        v = v.removeprefix("@")
        if not _USERNAME.match(v):
            raise InvalidIdentifier("usernames are 3-40 characters of letters, digits, '.', '_' or '-'")
        return v
    if kind == "image":
        return v[:100] or "image"
    if kind == "city":
        v = " ".join(v.split())
        if not 2 <= len(v) <= 60 or any(ch.isdigit() for ch in v):
            raise InvalidIdentifier("give the name of a city or town (2-60 letters)")
        return v
    if kind == "workplace":
        v = " ".join(v.split())
        if not 2 <= len(v) <= 100:
            raise InvalidIdentifier("give an employer or school name (2-100 characters)")
        return v
    if kind == "birth_year":
        if not re.fullmatch(r"\d{4}", v) or not 1900 <= int(v) <= date.today().year:
            raise InvalidIdentifier("give a four-digit birth year")
        return v
    raise InvalidIdentifier(f"unknown identifier kind {kind!r}")


def index_form(kind: str, normalized: str) -> str:
    """The form that goes into the blind index; equality lookups match on this."""
    return normalized if kind in {"phone", "image", "birth_year"} else normalized.casefold()
