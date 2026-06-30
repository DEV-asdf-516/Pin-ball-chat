import difflib
import json
import re
import sys


BAD_CONTROL = [
    "너는 고개를 끄덕였다",
    "너는 내 손을 잡았다",
    "너는 결국 따라왔다",
    "사용자는 아무 말 없이 복종했다",
]

BAD_UNSAFE = ["자해", "불법행위", "혐오", "비동의", "성적 강요"]


def token_count(text):
    return len(text.split())


def keep_pair(pair):
    chosen_len = token_count(pair["chosen"])
    rejected_len = token_count(pair["rejected"])
    if chosen_len < 5 or rejected_len < 5:
        return False
    if chosen_len > rejected_len * 1.8:
        return False
    if difflib.SequenceMatcher(None, pair["chosen"], pair["rejected"]).ratio() > 0.92:
        return False
    if any(s in pair["chosen"] for s in BAD_CONTROL):
        return False
    if any(re.search(s, pair["chosen"]) for s in BAD_UNSAFE):
        return False
    return True


def main():
    for line in sys.stdin:
        pair = json.loads(line)
        if keep_pair(pair):
            print(json.dumps(pair, ensure_ascii=False))


if __name__ == "__main__":
    main()
