import time


def utc_now_string():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
