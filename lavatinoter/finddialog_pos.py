"""Python string index <-> QTextCursor position mapping (UTF-16 units)."""
import bisect


class PosMap:
    """Maps Python string indexes to QTextCursor positions (UTF-16 units). Identity unless the text has emoji etc."""

    def __init__(self, text):
        self.astral = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF] if not text.isascii() else []

    def to_q(self, i):
        return i + bisect.bisect_left(self.astral, i) if self.astral else i

    def to_py(self, q):
        if not self.astral:
            return q
        lo, hi = 0, len(self.astral)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.astral[mid] + mid < q:
                lo = mid + 1
            else:
                hi = mid
        return q - lo
