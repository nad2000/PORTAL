# DATE_FORMAT = "d/m/Y"
DATE_FORMAT = "j/n/Y"
# TIME_FORMAT = "H:i"
TIME_FORMAT = "g:i A"
DATETIME_FORMAT = f"{DATE_FORMAT} {TIME_FORMAT}"
SHORT_DATETIME_FORMAT = DATETIME_FORMAT
SHORT_DATE_FORMAT = DATE_FORMAT
DATE_INPUT_FORMATS = [
    "%d/%m/%Y",  # '1/25/2006'
    "%Y-%m-%d",  # '2006-10-25'
    "%m/%d/%y",  # '10/25/06'
    "%b %d %Y",  # 'Oct 25 2006'
    "%b %d, %Y",  # 'Oct 25, 2006'
    "%d %b %Y",  # '25 Oct 2006'
    "%d %b, %Y",  # '25 Oct, 2006'
    "%B %d %Y",  # 'October 25 2006'
    "%B %d, %Y",  # 'October 25, 2006'
    "%d %B %Y",  # '25 October 2006'
    "%d %B, %Y",  # '25 October, 2006'
    "%m/%d/%Y",  # '10/25/2006'
]
DATETIME_INPUT_FORMATS = [
    "%d/%m/%Y %g:%i %A",  # '1/25/2006 5:30 PM'
    "%Y-%m-%d %H:%M:%S",  # '2006-10-25 14:30:59'
    "%Y-%m-%d %H:%M:%S.%f",  # '2006-10-25 14:30:59.000200'
    "%Y-%m-%d %H:%M",  # '2006-10-25 14:30'
    "%m/%d/%y %H:%M:%S",  # '10/25/06 14:30:59'
    "%m/%d/%y %H:%M",  # '10/25/06 14:30'
    "%b %d %Y %H:%M:%S",  # 'Oct 25 2006 14:30:59'
    "%b %d %Y %H:%M",  # 'Oct 25 2006 14:30'
    "%b %d, %Y %H:%M:%S",  # 'Oct 25, 2006 14:30:59'
    "%b %d, %Y %H:%M",  # 'Oct 25, 2006 14:30'
    "%d %b %Y %H:%M:%S",  # '25 Oct 2006 14:30:59'
    "%d %b %Y %H:%M",  # '25 Oct 2006 14:30'
    "%d %b, %Y %H:%M:%S",  # '25 Oct, 2006 14:30:59'
    "%d %b, %Y %H:%M",  # '25 Oct, 2006 14:30'
    "%B %d %Y %H:%M:%S",  # 'October 25 2006 14:30:59'
    "%B %d %Y %H:%M",  # 'October 25 2006 14:30'
    "%B %d, %Y %H:%M",  # 'October 25, 2006 14:30:59'
    "%B %d, %Y %H:%M",  # 'October 25, 2006 14:30'
    "%d %B %Y %H:%M:%S",  # '25 October 2006 14:30:59'
    "%d %B %Y %H:%M",  # '25 October 2006 14:30'
    "%d %B, %Y %H:%M:%S",  # '25 October, 2006 14:30:59'
    "%d %B, %Y %H:%M",  # '25 October, 2006 14:30'
    "%m/%d/%Y %H:%M:%S",  # '10/25/2006 14:30:59'
    "%m/%d/%Y %H:%M",  # '10/25/2006 14:30'
    "%n/%j/%Y %H:%M",  # '1/5/2006 14:30'
]
