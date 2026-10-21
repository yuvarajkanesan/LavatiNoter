"""Plugins are loaded from files, so the packaged app only has the standard modules the .spec files list for them."""
import glob
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PluginImportTests(unittest.TestCase):
    def test_builtin_plugin_imports_are_packaged(self):
        stdlib = set(sys.stdlib_module_names)
        for spec_name in ("LavatiNoter.spec", "LavatiNoterPortable.spec"):
            with open(os.path.join(ROOT, spec_name), encoding="utf-8") as f:
                spec = f.read()
            listed = set(re.findall(r'"([\w.]+)"', spec[spec.index("PLUGIN_MODULES"):spec.index("a = Analysis(")]))
            for path in glob.glob(os.path.join(ROOT, "builtin_plugins", "*.py")) + glob.glob(os.path.join(ROOT, "sample_plugins", "*.py")):
                with open(path, encoding="utf-8") as f:
                    for mod in re.findall(r"^\s*(?:import|from)\s+([\w.]+)", f.read(), re.M):
                        top = mod.split(".")[0]
                        if top in stdlib:
                            self.assertTrue(mod in listed or top in listed, f"{os.path.basename(path)} imports {mod}, missing from {spec_name}")


if __name__ == "__main__":
    unittest.main()
