"""초록 CI와 Sol 승인 코멘트가 있는 PR을 자동으로 squash 머지한다."""
import json
import subprocess
import sys


def main(pr: str) -> int:
    info = json.loads(subprocess.check_output(["gh", "pr", "view", pr, "--json", "statusCheckRollup,comments"]))
    if all(c["conclusion"] == "SUCCESS" for c in info["statusCheckRollup"]):
        subprocess.check_call(["gh", "pr", "merge", pr, "--squash", "--auto"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
