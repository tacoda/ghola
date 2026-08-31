"""A credential never reaches a file.

Imports nothing from ladder, so it runs standalone:

    python3 team/rules/no-secrets.py some_file.py
"""

import re
import sys

# Prefixes that are credentials wherever they appear, and the two PEM headers.
# Deliberately narrow: a pattern that fires on the word "key" would be switched
# off within a week, and a rule people switch off is worse than no rule.
PATTERNS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), "an Anthropic key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "an OpenAI-style key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "a GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "an AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
)

# An assignment from the environment is how a credential SHOULD arrive, so it is
# never a finding. Without this the rule fires on the correct pattern and teaches
# people that it is wrong.
FROM_ENV = re.compile(r"(os\.environ|getenv|ENV\[|process\.env|\$\{?[A-Z_]+\}?)")


def check(path: str, content: str, context: dict) -> list:
    findings = []
    for number, line in enumerate(content.splitlines(), 1):
        if FROM_ENV.search(line):
            continue
        for pattern, what in PATTERNS:
            if pattern.search(line):
                findings.append({"line": number, "why": f"{what} in source"})
                break
    return findings


def _self_check() -> None:
    assert check("a.py", "KEY = 'sk-ant-abcdefgh12345678'", {}), "should catch a literal"
    assert not check("a.py", "KEY = os.environ['ANTHROPIC_API_KEY']", {}), "env is correct"
    assert not check("a.py", "# the api key lives in .env", {}), "prose is not a key"
    assert check("a.py", "-----BEGIN RSA PRIVATE KEY-----", {})[0]["line"] == 1
    print("no-secrets: ok")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for found in check(sys.argv[1], open(sys.argv[1]).read(), {}):
            print(f"{sys.argv[1]}:{found['line']}: {found['why']}")
    else:
        _self_check()
