"""Language detection from the text:  python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lavatinoter.detect import guess_language  # noqa: E402

SAMPLES = {
    "Python": "import os\n\ndef greet(name):\n    print('hi', name)\n\nclass A:\n    def run(self):\n        return self.x\n\nif __name__ == '__main__':\n    greet('x')\n",
    "JavaScript": "const items = [1, 2, 3];\nfunction total(list) {\n  return list.reduce((a, b) => a + b, 0);\n}\nconsole.log(total(items));\n",
    "TypeScript": "interface User {\n  name: string;\n  age: number;\n}\nconst u: User = { name: 'a', age: 3 };\nfunction f(x: number): string { return String(x); }\n",
    "Java": "package demo;\nimport java.util.List;\npublic class Main {\n  public static void main(String[] args) {\n    System.out.println(\"hi\");\n  }\n}\n",
    "C#": "using System;\nnamespace Demo {\n  public class P {\n    public string Name { get; set; }\n    static void Main() { Console.WriteLine(\"hi\"); }\n  }\n}\n",
    "C / C++": "#include <stdio.h>\nint main(void) {\n  printf(\"hello\\n\");\n  return 0;\n}\n",
    "Go": "package main\n\nimport \"fmt\"\n\nfunc main() {\n  x := 5\n  fmt.Println(x)\n}\n",
    "Rust": "use std::collections::HashMap;\n\nfn main() {\n    let mut m = HashMap::new();\n    m.insert(1, 2);\n    println!(\"{:?}\", m);\n}\n",
    "PHP": "<?php\n$name = 'x';\necho \"Hello $name\";\n?>\n",
    "Ruby": "class Greeter\n  attr_accessor :name\n  def hello\n    puts \"hi #{name}\"\n  end\nend\n",
    "SQL": "SELECT id, name FROM users WHERE age > 30 ORDER BY name;\nINSERT INTO users (id) VALUES (1);\n",
    "HTML / XML": "<!DOCTYPE html>\n<html>\n<body>\n<div class=\"a\"><p>Hello</p></div>\n</body>\n</html>\n",
    "CSS": ".card {\n  margin: 0;\n  padding: 4px;\n  color: #333;\n}\n@media (max-width: 600px) { .card { display: none; } }\n",
    "JSON": '{"a": [1, 2, {"b": null}], "c": "x"}',
    "YAML": "name: ci\non:\n  push:\n    branches: [main]\njobs:\n  build:\n    runs-on: ubuntu\n    steps:\n      - uses: actions/checkout@v4\n",
    "Markdown": "# Title\n\nSome **bold** text and a [link](http://x.y).\n\n- item one\n- item two\n\n```\ncode\n```\n",
    "PowerShell / Shell": "#!/bin/bash\nset -e\necho \"hi\"\nfor f in *.txt; do\n  cat $f\ndone\n",
    "Batch": "@echo off\nset X=1\necho %X%\ngoto :end\n:end\npause\n",
    "Dockerfile": "FROM python:3.12\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\nCMD [\"python\", \"main.py\"]\n",
    "Diff / Patch": "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n-old\n+new\n",
    "Log": "2026-10-16 10:21:03 INFO server started\n2026-10-16 10:21:04 ERROR failed to connect\n2026-10-16 10:21:05 WARN retrying\n",
    "Lua": "local function add(a, b)\n  return a + b\nend\nprint(add(1, 2))\n",
    "INI / TOML / Properties": "[server]\nhost = 127.0.0.1\nport = 8080\n\n[db]\nname = test\n",
}
PROSE = ["Hi, this is a note about the meeting tomorrow. We need to talk about the budget and the schedule.\nPlease bring your notes.\n",
         "Shopping list: milk, eggs, bread.\nCall mom on Sunday.\nBuy a gift for Sam.\n", "hello", "Dear team,\nThanks for your hard work this week.\nBest regards,\nAlex\n"]


class DetectTests(unittest.TestCase):
    def test_code_samples(self):
        for expect, text in SAMPLES.items():
            self.assertEqual(guess_language(text), expect, expect)

    def test_prose_is_not_code(self):
        for text in PROSE:
            self.assertIsNone(guess_language(text), text[:30])


if __name__ == "__main__":
    unittest.main()
