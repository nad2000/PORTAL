"""
Borrowed from ORCIDHUB: https://github.com/Royal-Society-of-New-Zealand/NZ-ORCID-Hub/
"""

import re
from collections import namedtuple
from datetime import date, datetime, timedelta

PARTIAL_DATE_REGEX = re.compile(r"\d+([/\-\.]\d+){,2}")
FUZZY_DATE_REGEX = re.compile(r"\d+([/\-\.]\d+){,2}")


class PartialDate(namedtuple("PartialDate", ["year", "month", "day"])):
    """Partial date (without month day or both month and month day."""

    def as_orcid_dict(self):
        """Return ORCID dictionary representation of the partial date."""
        if self.is_null:
            return None
        return dict(
            (
                (f, None if v is None else {"value": ("%04d" if f == "year" else "%02d") % v})
                for (f, v) in zip(self._fields, self)
            )
        )

    @property
    def is_null(self):
        """Test if if the date is undefined."""
        return self.year is None and self.month is None and self.day is None

    @classmethod
    def create(cls, value):
        """Create a partial date form ORCID dictionary representation or string.
        >>> PartialDate.create({"year": {"value": "2003"}}).as_orcid_dict()
        {'year': {'value': '2003'}, 'month': None, 'day': None}
        >>> PartialDate.create({"year": {"value": "2003"}}).year
        2003
        >>> PartialDate.create("2003").year
        2003
        >>> PartialDate.create("2003-03")
        2003-03
        >>> PartialDate.create("2003-07-14")
        2003-07-14
        >>> PartialDate.create("2003/03")
        2003-03
        >>> PartialDate.create("2003/07/14")
        2003-07-14
        >>> PartialDate.create("03/2003")
        2003-03
        >>> PartialDate.create("14/07/2003")
        2003-07-14
        """
        if value is None or value == {}:
            return None
        if isinstance(value, str):
            match = PARTIAL_DATE_REGEX.search(value)
            if not match:
                raise Exception(f"Wrong partial date value '{value}'")
            value0 = match[0]
            for sep in ["/", "."]:
                if sep in value0:
                    parts = value0.split(sep)
                    return cls(*[int(v) for v in (parts[::-1] if len(parts[-1]) > 2 else parts)])

            return cls(*[int(v) for v in value0.split("-")])

        return cls(
            **{k: int(v.get("value")) if v and v.get("value") else None for k, v in value.items()}
        )

    def as_datetime(self):
        """Get 'datetime' data representation."""
        return datetime(self.year, self.month, self.day)

    def __str__(self):
        """Get string representation."""
        if self.year is None:
            return ""
        else:
            res = "%04d" % int(self.year)
            if self.month:
                res += "-%02d" % int(self.month)
            else:
                res += "-%02d" % 1
            res += "-%02d" % int(self.day if self.day else 1)
            return res


class FuzzyDate(namedtuple("FuzzyDate", ["year", "month", "day"])):
    """Fuzzy date (without month day or both month and month day."""

    def as_orcid_dict(self):
        """Return ORCID dictionary representation of the partial date."""
        if self.is_null:
            return None
        return dict(
            (
                (f, None if v is None else {"value": ("%04d" if f == "year" else "%02d") % v})
                for (f, v) in zip(self._fields, self)
            )
        )

    @property
    def is_null(self):
        """Test if if the date is undefined."""
        return self.year is None and self.month is None and self.day is None

    @classmethod
    def create(cls, value):
        """Create a partial date form ORCID dictionary representation or string.
        >>> FuzzyDate.create({"year": {"value": "2003"}}).as_orcid_dict()
        {'year': {'value': '2003'}, 'month': None, 'day': None}
        >>> FuzzyDate.create({"year": {"value": "2003"}}).year
        2003
        >>> FuzzyDate.create("2003").year
        2003
        >>> FuzzyDate.create("2003-03")
        2003-03
        >>> FuzzyDate.create("2003-07-14")
        2003-07-14
        >>> FuzzyDate.create("2003/03")
        2003-03
        >>> FuzzyDate.create("2003/07/14")
        2003-07-14
        >>> FuzzyDate.create("03/2003")
        2003-03
        >>> FuzzyDate.create("14/07/2003")
        2003-07-14
        """
        if value is None or value == {}:
            return None
        if isinstance(value, str):
            match = PARTIAL_DATE_REGEX.search(value)
            if not match:
                raise Exception(f"Wrong partial date value '{value}'")
            value0 = match[0]
            for sep in ["/", "."]:
                if sep in value0:
                    parts = value0.split(sep)
                    return cls(*[int(v) for v in (parts[::-1] if len(parts[-1]) > 2 else parts)])

            return cls(*[int(v) for v in value0.split("-")])

        return cls(
            **{k: int(v.get("value")) if v and v.get("value") else None for k, v in value.items()}
        )

    def start_date(self):
        """Get 'date' data representation."""
        if self.year is None:
            return None
        return datetime(self.year, self.month or 1, self.day or 1)

    def end_date(self):
        """Get 'date' data representation."""
        if self.year is None:
            return None
        if self.month and self.month < 12:
            return date(self.year, self.month + 1, self.day or 1) - timedelta(1)
        return date(self.year, 12, self.day or 31)

    def as_datetime(self):
        """Get 'datetime' data representation."""
        return datetime(self.year, self.month, self.day)

    def __str__(self):
        """Get string representation."""
        if self.year is None:
            return ""
        else:
            res = "%04d" % int(self.year)
            if self.month:
                res += "-%02d" % int(self.month)
            else:
                res += "-%02d" % 1
            res += "-%02d" % int(self.day if self.day else 1)
            return res


FuzzyDate.__new__.__defaults__ = (None,) * len(FuzzyDate._fields)
PartialDate.__new__.__defaults__ = (None,) * len(PartialDate._fields)
