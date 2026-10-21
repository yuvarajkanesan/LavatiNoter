import csv
import datetime
import io
import json
import re

NAME = "Converters"
VERSION = "1.0"
DESCRIPTION = "Timestamps, CSV to Markdown / JSON, JSON to CSV, colours and number bases."


def rows(text):
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if r]


def ts_to_date(s):
    def one(m):
        n = int(m.group())
        if n > 10_000_000_000:
            n //= 1000
        return datetime.datetime.fromtimestamp(n, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return re.sub(r"\b\d{9,13}\b", one, s)


def date_to_ts(s):
    def one(m):
        d = datetime.datetime.fromisoformat(m.group().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return str(int(d.timestamp()))
    return re.sub(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?", one, s)


def csv_to_md(s):
    r = rows(s)
    if not r:
        raise ValueError("no rows")
    w = max(len(x) for x in r)
    r = [x + [""] * (w - len(x)) for x in r]
    widths = [max(3, max(len(x[i]) for x in r)) for i in range(w)]

    def line(x):
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(x)) + " |"
    return "\n".join([line(r[0]), "| " + " | ".join("-" * wd for wd in widths) + " |"] + [line(x) for x in r[1:]])


def csv_to_json(s):
    r = rows(s)
    return json.dumps([dict(zip(r[0], x)) for x in r[1:]], indent=2, ensure_ascii=False)


def json_to_csv(s):
    data = json.loads(s)
    if isinstance(data, dict):
        data = [data]
    keys = list(dict.fromkeys(k for d in data for k in d))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=keys, lineterminator="\n")
    w.writeheader()
    for d in data:
        w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in d.items()})
    return out.getvalue().rstrip("\n")


def register(api):
    def safe(fn):
        def run():
            try:
                api.transform(fn)
            except (ValueError, KeyError, TypeError, csv.Error, IndexError) as e:
                api.flash(f"Could not convert: {e}")
        return run

    api.add_command("Timestamp: Unix time to date", safe(ts_to_date))
    api.add_command("Timestamp: date to Unix time", safe(date_to_ts))
    api.add_command("CSV: to Markdown table", safe(csv_to_md))
    api.add_command("CSV: to JSON", safe(csv_to_json))
    api.add_command("JSON: to CSV", safe(json_to_csv))
    api.add_command("Colour: #rrggbb to rgb()", safe(lambda s: re.sub(
        r"#([0-9a-fA-F]{6})\b", lambda m: "rgb({}, {}, {})".format(*(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))), s)))
    api.add_command("Colour: rgb() to #rrggbb", safe(lambda s: re.sub(
        r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", lambda m: "#{:02x}{:02x}{:02x}".format(*(min(255, int(x)) for x in m.groups())), s)))
    api.add_command("Numbers: decimal to hex", safe(lambda s: re.sub(r"\b\d+\b", lambda m: hex(int(m.group())), s)))
    api.add_command("Numbers: hex to decimal", safe(lambda s: re.sub(r"\b0[xX][0-9a-fA-F]+\b", lambda m: str(int(m.group(), 16)), s)))
    api.add_command("Numbers: decimal to binary", safe(lambda s: re.sub(r"\b\d+\b", lambda m: bin(int(m.group())), s)))
