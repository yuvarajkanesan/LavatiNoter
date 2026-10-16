"""A plain hex dump (offset, hex bytes, ASCII) for binary files."""

MAX_HEX_BYTES = 8 * 1024 * 1024


def hex_dump(data, base=0, width=16):
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexes = " ".join(f"{b:02x}" for b in chunk)
        mid = hexes[:23] + " " + hexes[23:] if len(chunk) > 8 else hexes
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:08x}  {mid:<49} |{ascii_}|")
    return "\n".join(lines) + ("\n" if lines else "")


def read_hex(path):
    """-> (text, bytes shown, file size)."""
    import os
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read(MAX_HEX_BYTES)
    return hex_dump(data), len(data), size
