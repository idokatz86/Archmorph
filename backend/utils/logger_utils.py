def sanitize_log(val):
    if not isinstance(val, str):
        return val
    return val.replace('\n', '').replace('\r', '')
