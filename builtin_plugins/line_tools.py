import random
import re

NAME = "Line tools"
VERSION = "1.0"
DESCRIPTION = "Number, reverse, shuffle, join, split, filter and decorate lines."


def first_number(line):
    m = re.search(r"-?\d+\.?\d*", line)
    return float(m.group()) if m else float("inf")


def register(api):
    t = api.transform

    def lines(fn):
        return lambda: t(lambda s: "\n".join(fn(s.split("\n"))))

    def asking(prompt, make, default=""):
        def run():
            v = api.ask(prompt, default)
            if v:
                t(lambda s: "\n".join(make(v)(s.split("\n"))))
        return run

    def join():
        sep = api.ask("Separator between the lines:", ", ")
        if sep is not None:
            t(lambda s: sep.join(s.split("\n")))

    def split():
        sep = api.ask("Split wherever this appears:", ",")
        if sep:
            t(lambda s: s.replace(sep, "\n"))

    api.add_command("Number lines", lines(lambda ls: [f"{i}. {l}" for i, l in enumerate(ls, 1)]))
    api.add_command("Remove line numbers", lines(lambda ls: [re.sub(r"^\s*\d+[.):\t ]\s?", "", l) for l in ls]))
    api.add_command("Reverse the order of lines", lines(lambda ls: ls[::-1]))
    api.add_command("Shuffle lines", lines(lambda ls: random.sample(ls, len(ls))))
    api.add_command("Sort lines by length", lines(lambda ls: sorted(ls, key=len)))
    api.add_command("Sort lines by the first number in them", lines(lambda ls: sorted(ls, key=first_number)))
    api.add_command("Join lines with a separator...", join)
    api.add_command("Split at a separator into lines...", split)
    api.add_command("Add a prefix to every line...", asking("Prefix:", lambda v: lambda ls: [v + l for l in ls], "- "))
    api.add_command("Add a suffix to every line...", asking("Suffix:", lambda v: lambda ls: [l + v for l in ls], ";"))
    api.add_command("Keep only lines containing...", asking("Keep lines that contain:", lambda v: lambda ls: [l for l in ls if v in l]))
    api.add_command("Delete lines containing...", asking("Delete lines that contain:", lambda v: lambda ls: [l for l in ls if v not in l]))
    api.add_command("Quote every line", lines(lambda ls: ['"' + l + '"' for l in ls]))
    api.add_command("Turn lines into a quoted, comma-separated list", lambda: t(lambda s: ", ".join('"' + l + '"' for l in s.split("\n") if l.strip())))
