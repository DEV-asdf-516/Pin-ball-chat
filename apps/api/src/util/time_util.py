import time


def utc_now_string() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
