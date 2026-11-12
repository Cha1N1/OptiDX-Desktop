"""Bound completed activity history without deleting unresolved recovery evidence."""

from pathlib import Path

HISTORY_LIMIT = 200
LOG_LIMIT = 8 * 1024 * 1024


def trim_history(records, directory, limit=HISTORY_LIMIT):
    def protected(record):
        if record.get("recovery_state") in {"manual", "interrupted"}:
            return True
        # Records written before recovery_state existed only carry text.
        value = (
            str(record.get("result", "")).lower() + " " + str(record.get("recovery", "")).lower()
        )
        return (
            record.get("result") == "Running"
            or "interrupted" in value
            or "manual recovery" in value
        )

    finished = [record for record in records if not protected(record)]
    keep = {id(record) for record in finished[-limit:]}
    result = []
    logs = (Path(directory) / "logs").resolve()
    for record in records:
        if protected(record) or id(record) in keep:
            result.append(record)
        elif record.get("log"):
            path = Path(record["log"])
            if not path.is_symlink() and path.parent.resolve() == logs:
                path.unlink(missing_ok=True)
    return result


def write_log(stream, text):
    stream.write(text)
    stream.flush()
    if stream.tell() > LOG_LIMIT:
        stream.seek(0)
        content = stream.read()
        stream.seek(0)
        stream.truncate()
        stream.write(
            "[Earlier output truncated; retaining recent activity]\n" + content[-LOG_LIMIT // 2 :]
        )
        stream.flush()
