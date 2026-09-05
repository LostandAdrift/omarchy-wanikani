"""Read-only local activity, retaining the latest 35 nonempty local days.

The UTC expression index narrows each read without freezing the user's current
time zone into stored aggregates. Sparse activity expands the range until the
same days as the original full-history GROUP BY are available.
"""

COMPLETIONS = "kind IN ('subject_complete','practice_complete')"
GROUPED = "SELECT date(created_at,'localtime') AS day,COUNT(*) AS count FROM events WHERE "
GROUP_LIMIT = " GROUP BY day ORDER BY day DESC LIMIT 35"


def activity(store):
    # One worker owns the database. Keep its background synchronization from
    # inserting between the endpoint and range queries, without a write lock.
    with store.lock:
        def full_history():
            return [dict(row) for row in store.rows(GROUPED + COMPLETIONS + GROUP_LIMIT)]

        latest = store.rows("""SELECT created_at,julianday(created_at) FROM events
          WHERE """ + COMPLETIONS + """ AND julianday(created_at) IS NOT NULL
          ORDER BY julianday(created_at) DESC LIMIT 1""")
        if not latest:
            # Empty history and unparseable dates retain the original NULL group.
            return full_history()
        oldest = store.rows("""SELECT julianday(created_at) FROM events
          WHERE """ + COMPLETIONS + """ AND julianday(created_at) IS NOT NULL
          ORDER BY julianday(created_at) ASC LIMIT 1""")[0][0]
        # Outside ordinary four-digit years, local-time conversion can overflow
        # and textual calendar ordering need not follow Julian-day ordering.
        if oldest < 1721425.5 or latest[0][1] >= 5373119.5:
            return full_history()
        days = 35
        while True:
            lower, boundary_day = store.rows("""SELECT value,date(value,'localtime') FROM
              (SELECT julianday(?,'localtime','start of day',?,'utc') AS value)""",
                (latest[0][0], "-" + str(days) + " days"))[0]
            if lower is None or boundary_day is None:
                return full_history()
            result = [dict(row) for row in store.rows(GROUPED + COMPLETIONS
                + " AND julianday(created_at)>=?" + GROUP_LIMIT, (lower,))]
            # A historical midnight offset change can make local midnight
            # ambiguous. Only return before exhaustion if the oldest selected
            # day lies strictly after the boundary, keeping its entire count.
            if len(result) >= 35 and (lower <= oldest or result[-1]["day"] > boundary_day):
                return result
            if lower <= oldest:
                null_count = store.rows("SELECT COUNT(*) FROM events WHERE " + COMPLETIONS
                    + " AND julianday(created_at) IS NULL")[0][0]
                return result + ([{"day": None, "count": null_count}] if null_count else [])
            days *= 2
