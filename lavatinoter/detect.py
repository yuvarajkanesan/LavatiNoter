"""Guesses the programming language of a piece of text (for new documents and files without a known extension)."""
import json
import re

# language name (as in highlighter.LANGS) -> [(regex, weight)]. Each regex counts at most 3 times.
SIGNATURES = {
    "Python": [(r"^\s*def \w+\(.*\)\s*(->.*)?:", 4), (r"^\s*class \w+(\(.*\))?:", 4), (r"^\s*(from [\w.]+ )?import [\w., ]+$", 2),
               (r"if __name__ == ['\"]__main__['\"]", 5), (r"^\s*(elif|else|try|except|finally|with .+ as .+|for .+ in .+|while .+):\s*$", 2),
               (r"\bself\.\w+", 1), (r"^\s*print\(", 1), (r"^\s*@\w+", 1), (r"\bNone\b|\bTrue\b|\bFalse\b", 1), (r"^\s*#.*$", 0.3)],
    "JavaScript": [(r"\bfunction\s*\w*\s*\(", 3), (r"=>\s*[{(\w]", 2), (r"\b(const|let|var)\s+\w+\s*=", 2), (r"console\.(log|error)\(", 4),
                   (r"\brequire\(['\"]", 3), (r"^\s*import .+ from ['\"]", 3), (r"\bexport (default |const |function )", 3),
                   (r"document\.\w+|window\.\w+", 2), (r"===|!==", 2), (r"\bnew Promise\b|\basync function\b|\bawait\b", 1)],
    "TypeScript": [(r":\s*(string|number|boolean|any|void|unknown)\b", 3), (r"\binterface \w+\s*\{", 4), (r"\btype \w+\s*=", 3),
                   (r"\bimport .+ from ['\"]", 1), (r"\b(readonly|private|public) \w+:", 2), (r"<\w+(\[\])?>\(", 1), (r"\bas (string|number|const|any)\b", 2),
                   (r"\benum \w+\s*\{", 2)],
    "Java": [(r"\bpublic (static )?(final )?(class|void|int|String)\b", 3), (r"System\.out\.print", 5), (r"^package [\w.]+;", 4),
             (r"^import java\.", 5), (r"\bpublic static void main\b", 6), (r"@Override", 3), (r"\bnew \w+<.*>\(", 1)],
    "C#": [(r"^using System", 6), (r"\bnamespace [\w.]+", 3), (r"Console\.Write(Line)?\(", 5), (r"\bpublic (static |async )?(void|class|string|int|Task)", 2),
           (r"\{ get; (private )?set; \}", 5), (r"\bvar \w+ = new\b", 2), (r"\[\w+(\(.*\))?\]\s*$", 1)],
    "C / C++": [(r"^\s*#include\s*[<\"]", 6), (r"\bint main\s*\(", 5), (r"std::\w+", 4), (r"\bprintf\(", 3), (r"cout\s*<<|cin\s*>>", 5),
                (r"\b(unsigned|signed)\s+(int|long|char)\b", 2), (r"->\w+|\bnullptr\b|\bstruct \w+\s*\{", 2), (r"^\s*#(define|ifdef|ifndef|endif|pragma)\b", 3)],
    "Go": [(r"^package \w+\s*$", 5), (r"\bfunc (\(\w+ \*?\w+\) )?\w+\(", 4), (r":=", 3), (r"\bfmt\.\w+\(", 5), (r"^import \(\s*$", 4),
           (r"\bgo func\(|\bdefer \w+|\bchan \w+", 3)],
    "Rust": [(r"\bfn \w+\s*(<.*>)?\(", 4), (r"\blet mut \w+", 5), (r"println!\(|vec!\[|format!\(", 5), (r"^use [\w:]+(::\{.*\})?;", 4), (r"\bimpl(<.*>)? \w+", 3),
             (r"->\s*(Result|Option|Self|&|u\d+|i\d+|String)", 2), (r"#\[derive\(", 5), (r"\bpub (fn|struct|enum|mod)\b", 4)],
    "Kotlin": [(r"\bfun \w+\(", 5), (r"\b(val|var) \w+(:\s*\w+)?\s*=", 2), (r"\bdata class\b|\bcompanion object\b|\bwhen\s*\(", 5), (r"println\(", 1)],
    "Swift": [(r"\bfunc \w+\(.*\)\s*(->.*)?\{", 4), (r"^import (Foundation|UIKit|SwiftUI)", 6), (r"\b(let|var) \w+: \w+", 2), (r"\bguard let\b|\bif let\b", 4)],
    "PHP": [(r"<\?php", 8), (r"\$\w+\s*=", 2), (r"\becho\s+.*;", 2), (r"->\w+\(|::\w+\(", 1), (r"\bfunction \w+\(\$", 3)],
    "Ruby": [(r"^\s*def \w+[?!]?(\(.*\))?\s*$", 3), (r"^\s*end\s*$", 3), (r"\bputs\s+", 3), (r"^\s*require ['\"]", 3), (r"attr_(accessor|reader|writer)", 5),
             (r"\bdo\s*\|\w+\|", 4), (r"^\s*class \w+( < \w+)?\s*$", 3)],
    "Lua": [(r"\blocal (function )?\w+", 4), (r"^\s*end\s*$", 1), (r"\bthen\s*$", 2), (r"\bfunction \w+(\.\w+)*\(.*\)\s*$", 2), (r"^\s*--", 1)],
    "Perl": [(r"^#!/usr/bin/(env )?perl", 8), (r"\bmy\s+[$@%]\w+", 5), (r"^use (strict|warnings)", 6), (r"\bsub \w+\s*\{", 4)],
    "R": [(r"<-", 3), (r"\blibrary\(\w+\)", 5), (r"\bfunction\(.*\)\s*\{", 1), (r"\bdata\.frame\(|\bggplot\(", 5)],
    "SQL": [(r"(?i)^\s*select\b.*\bfrom\b", 6), (r"(?i)^\s*(insert into|update \w+ set|delete from|create table|alter table|drop table)\b", 6),
            (r"(?i)\b(where|group by|order by|inner join|left join)\b", 2), (r"(?i)^\s*--", 0.5)],
    "HTML / XML": [(r"(?i)<!DOCTYPE html", 8), (r"(?i)<html[\s>]", 6), (r"(?i)</?(div|span|p|body|head|script|style|a|ul|li|table|h[1-6])[\s>]", 3),
                   (r"^\s*<\?xml", 8), (r"</\w[\w:.-]*>", 1), (r"<\w[\w:.-]*(\s+[\w:.-]+=\"[^\"]*\")*\s*/?>", 1)],
    "CSS": [(r"[.#]?[\w-]+(\s*[,>+~]\s*[.#]?[\w-]+)*\s*\{", 1), (r"^\s*[\w-]+\s*:\s*[^;{}]+;\s*$", 1.5), (r"@(media|import|keyframes|font-face)\b", 5),
            (r"\b(margin|padding|color|background|display|font-size|border)\s*:", 3)],
    "YAML": [(r"^\s*[\w.-]+:\s*(\S.*)?$", 1, 10), (r"^\s*-\s+\w", 0.7), (r"^---\s*$", 3), (r"^\s*[\w-]+:\s*\|\s*$", 3)],
    "INI / TOML / Properties": [(r"^\[[\w. -]+\]\s*$", 4), (r"^\s*[\w.-]+\s*=\s*.+$", 1), (r"^\s*[;#].*$", 0.3), (r"^\[\[[\w.-]+\]\]\s*$", 4)],
    "Markdown": [(r"^#{1,6}\s+\S", 2), (r"^\s*[-*+]\s+\S", 1), (r"\[[^\]]+\]\([^)]+\)", 3), (r"^```", 4), (r"\*\*[^*]+\*\*", 2), (r"^>\s+\S", 1),
                 (r"^\d+\.\s+\S", 1)],
    "PowerShell / Shell": [(r"^#!/(usr/)?bin/(env )?(ba|z|da)?sh", 8), (r"\$env:\w+", 5), (r"\b(Get|Set|New|Remove|Write)-\w+", 5), (r"^\s*(echo|export|cd|ls|grep|sudo|apt|chmod) ", 2),
                           (r"\$\{?\w+\}?", 1), (r"\bparam\s*\(", 3), (r"\bfi\s*$|\bdone\s*$|\besac\s*$", 4), (r"^\s*\[\[?\s+.*\]\]?\s*(&&|;|then)", 3)],
    "Batch": [(r"(?i)^@echo (off|on)", 8), (r"(?i)^\s*(rem|goto|setlocal|endlocal|pause|call|cls)\b", 3), (r"%\w+%|%~\w+", 3), (r"^:\w+\s*$", 3)],
    "Dockerfile": [(r"^FROM \S+", 8), (r"^(RUN|COPY|ADD|CMD|ENTRYPOINT|EXPOSE|WORKDIR|ENV|ARG|LABEL) ", 3)],
    "Diff / Patch": [(r"^diff --git ", 8), (r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@", 8), (r"^(---|\+\+\+) \S+", 4), (r"^[+-][^+-].*$", 0.3)],
    "Log": [(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", 4), (r"\b(INFO|WARN(ING)?|ERROR|DEBUG|TRACE|FATAL)\b", 2), (r"^\[\d{1,2}/\w{3}/\d{4}", 4),
            (r"\bat [\w.$]+\([\w.]+:\d+\)", 3), (r"^\w{3} +\d+ \d\d:\d\d:\d\d ", 4)],
}
SAMPLE = 40000
MIN_SCORE = 4


def guess_language(text):
    """The language name for `text`, or None when it looks like ordinary prose / is too short to tell."""
    text = text.strip("\ufeff")
    sample = text[:SAMPLE]
    if len(sample.strip()) < 12:
        return None
    head = sample.lstrip()
    if head[:1] in "{[" and len(sample) < 2_000_000:
        try:
            json.loads(text if len(text) < 2_000_000 else sample)
            return "JSON"
        except ValueError:
            pass
    first = sample.split("\n", 1)[0]
    if first.startswith("#!"):
        for needle, name in (("python", "Python"), ("node", "JavaScript"), ("ruby", "Ruby"), ("perl", "Perl"), ("php", "PHP"),
                             ("bash", "PowerShell / Shell"), ("/sh", "PowerShell / Shell"), ("zsh", "PowerShell / Shell"), ("lua", "Lua")):
            if needle in first:
                return name
    scores = {}
    for lang, sigs in SIGNATURES.items():
        total = 0.0
        for sig in sigs:
            rx, weight = sig[0], sig[1]
            cap = sig[2] if len(sig) > 2 else 3
            total += weight * min(len(re.findall(rx, sample, re.M)), cap)
        if total:
            scores[lang] = total
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top < MIN_SCORE or top < second * 1.25:
        return None
    # YAML, INI, Markdown and CSS match a lot of ordinary text: they need a clear lead over "no language"
    if best in ("YAML", "INI / TOML / Properties", "CSS") and top < 6:
        return None
    if best == "TypeScript" and scores.get("JavaScript", 0) * 1.0 >= top:
        return "JavaScript"
    return best
