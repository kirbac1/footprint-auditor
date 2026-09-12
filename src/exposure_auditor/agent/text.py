"""Text folding shared by the scope guard and the matching rules.

Both have to treat "Uğur Kırbaç", "Ugur Kirbac" and "ugur-kirbac" as the same
name: one when deciding whether a query is in scope, the other when deciding
whether a page shows it. Keeping the rule in one place is what stops those two
answers from drifting apart.
"""

import re
import unicodedata

# Turkish dotless/dotted i and similar pairs do not reduce to ASCII by
# stripping marks alone; casefold first, then strip, then map what is left.
_EQUIVALENT = str.maketrans({"ı": "i", "İ": "i", "ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "ß": "ss"})


def strip_marks(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Case- and accent-insensitive, URL separators as spaces, so the name
    'Meikäläinen' matches the slug 'maija-meikalainen'."""
    t = re.sub(r"[-_./+%]+", " ", strip_marks(text.casefold().translate(_EQUIVALENT)))
    return " ".join(t.split())
