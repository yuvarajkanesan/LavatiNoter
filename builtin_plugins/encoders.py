import base64
import binascii
import hashlib
import html
import json
import urllib.parse

NAME = "Encoders and hashes"
VERSION = "1.0"
DESCRIPTION = "Base64, URL, HTML and Unicode encoding and decoding, hex, JSON string escaping, and MD5 / SHA hashes."


def register(api):
    t = api.transform

    def guarded(fn):
        def run():
            try:
                t(fn)
            except (ValueError, binascii.Error, UnicodeError) as e:
                api.flash(f"Could not convert: {e}")
        return run

    api.add_command("Base64: encode", guarded(lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii")))
    api.add_command("Base64: decode", guarded(lambda s: base64.b64decode(s.strip().encode("ascii")).decode("utf-8", "replace")))
    api.add_command("URL: encode", guarded(lambda s: urllib.parse.quote(s, safe="")))
    api.add_command("URL: decode", guarded(lambda s: urllib.parse.unquote(s)))
    api.add_command("HTML: escape & < > quotes", guarded(lambda s: html.escape(s)))
    api.add_command("HTML: unescape", guarded(lambda s: html.unescape(s)))
    api.add_command("Unicode: to \\uXXXX escapes", guarded(lambda s: "".join(c if ord(c) < 128 else "\\u%04x" % ord(c) if ord(c) < 0x10000 else "\\U%08x" % ord(c) for c in s)))
    api.add_command("Unicode: from \\uXXXX escapes", guarded(lambda s: s.encode("latin-1", "backslashreplace").decode("unicode_escape")))
    api.add_command("Hex: text to hex bytes", guarded(lambda s: s.encode("utf-8").hex(" ")))
    api.add_command("Hex: hex bytes to text", guarded(lambda s: bytes.fromhex(s.strip()).decode("utf-8", "replace")))
    api.add_command("JSON: escape as a string", guarded(lambda s: json.dumps(s, ensure_ascii=False)[1:-1]))
    api.add_command("JSON: unescape a string", guarded(lambda s: json.loads('"' + s.replace("\n", "\\n") + '"')))

    def digest(name):
        def run():
            h = hashlib.new(name, (api.selection() or api.text()).encode("utf-8")).hexdigest()
            api.copy(h)
            api.flash(f"{name.upper()} copied: {h}")
        return run
    for n in ("md5", "sha1", "sha256", "sha512"):
        api.add_command(f"Hash: {n.upper()} of the selection (copied)", digest(n))
