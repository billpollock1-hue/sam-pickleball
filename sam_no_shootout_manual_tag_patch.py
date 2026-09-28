#!/usr/bin/env python3
"""
Patch: distinguishes manually-recorded no-shootout dates from the ones
check_no_shootout.py generates automatically, so its self-correction logic
never silently reverts a deliberate cancellation.

Real incident, 2026-09-28: Bill recorded 2026-09-28 as "no shootout" via
the admin panel (confirmed saved -- file mtime 11:40, matching the click).
A later run_all.sh cycle called check_no_shootout.py's
remove_stale_no_shootout_entry(), which assumes ANY no-shootout entry for
today is a stale early-morning low-signup read and removes it once the
count recovers above the minimum. It can't tell that entry apart from a
deliberate admin cancellation, because both are written to the same file
in the same one-column format. The entry was silently erased; 9/29's
court-assignment preview stayed marked preliminary as a result, since the
pipeline still considered 9/28 a live playdate.

Fix: data/no_shootout_dates.csv gains a second column, "source" -- "manual"
for admin-panel entries, "auto" for check_no_shootout.py's own. The
self-correction logic now only removes entries whose source is "auto".
Existing rows (pre-dating this fix) are migrated with an empty source,
preserving their current (removable) behavior exactly -- this only ever
matters for TODAY's date in the removal check, so it's inert for the four
existing past dates and only changes behavior going forward.

data/partial_shootout_dates.csv is untouched: nothing auto-removes from it,
so it has no equivalent race to guard against.

Run once from the repo root: python3 sam_no_shootout_manual_tag_patch.py
Safe to re-run: the CSV migration checks the header first; both code
patches assert their anchors match exactly once.
"""
import csv
from pathlib import Path

server_path = Path("launcher/launcher_server.py")
check_path = Path("assignments/check_no_shootout.py")
csv_path = Path("data/no_shootout_dates.csv")

server = server_path.read_text(encoding="utf-8")
check = check_path.read_text(encoding="utf-8")


def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    return text.replace(old, new)


# ------------------------------------------------------------- CSV data ---

if csv_path.exists():
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0] if rows else ["date"]
    if header == ["date", "source"]:
        print("CSV already migrated -- leaving it alone.")
    else:
        assert header == ["date"], f"unexpected header, not migrating automatically: {header}"
        data_rows = [r for r in rows[1:] if r and r[0].strip()]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")  # match this codebase's plain \n CSVs
            w.writerow(["date", "source"])
            for r in data_rows:
                w.writerow([r[0].strip(), ""])  # unknown provenance, pre-fix
        print(f"CSV migrated: {len(data_rows)} existing row(s) given an empty source.")
else:
    print("No existing CSV -- nothing to migrate (a fresh one will get the new header).")

# -------------------------------------------------------- launcher_server ---

if 'f.write(f"{date_str},manual' in server:
    print("launcher_server.py already patched -- skipping.")
else:
    # 1. get_recorded_dates(): parse just the date field, tolerant of the
    #    old one-column and new two-column formats alike.
    old_parse = (
        '        lines = csv_path.read_text().splitlines()[1:]  # skip header\n'
        '        for line in lines:\n'
        '            date_str = line.strip()\n'
        '            if date_str:\n'
        '                entries.append({"date": date_str, "type": date_type})\n'
    )
    new_parse = (
        '        lines = csv_path.read_text().splitlines()[1:]  # skip header\n'
        '        for line in lines:\n'
        '            date_str = line.split(",")[0].strip()  # tolerant of an optional source column\n'
        '            if date_str:\n'
        '                entries.append({"date": date_str, "type": date_type})\n'
    )
    server = replace_once(server, old_parse, new_parse, "get_recorded_dates parse")

    # 2. _handle_record_date's "none" branch: write with source="manual"
    #    instead of the shared single-column _append_csv_date helper.
    old_none_branch = (
        '        if date_type == "none":\n'
        '            if not self._append_csv_date(NO_SHOOTOUT_CSV, date_str):\n'
        '                self._send_json({"error": f"{date_str} is already recorded"}, status=409)\n'
        '                return\n'
    )
    new_none_branch = (
        '        if date_type == "none":\n'
        '            # Tagged "manual" (distinct from check_no_shootout.py\'s own\n'
        '            # "auto" entries) so its self-correction logic never silently\n'
        '            # reverts a deliberate admin-panel cancellation -- real\n'
        '            # incident 2026-09-28: an auto-removal erased one within\n'
        '            # the same run_all.sh cycle.\n'
        '            existing_dates = set()\n'
        '            if NO_SHOOTOUT_CSV.exists():\n'
        '                existing_dates = {\n'
        '                    line.split(",")[0].strip()\n'
        '                    for line in NO_SHOOTOUT_CSV.read_text().splitlines()[1:]\n'
        '                    if line.strip()\n'
        '                }\n'
        '            if date_str in existing_dates:\n'
        '                self._send_json({"error": f"{date_str} is already recorded"}, status=409)\n'
        '                return\n'
        '            if not NO_SHOOTOUT_CSV.exists():\n'
        '                NO_SHOOTOUT_CSV.write_text("date,source\\n")\n'
        '            with open(NO_SHOOTOUT_CSV, "a") as f:\n'
        '                f.write(f"{date_str},manual\\n")\n'
    )
    server = replace_once(server, old_none_branch, new_none_branch, "record-date none branch")
    server_path.write_text(server, encoding="utf-8")
    print("launcher_server.py updated successfully")

# -------------------------------------------------------- check_no_shootout ---

if 'source' in check.split("def record_no_shootout")[1].split("def ")[0]:
    print("check_no_shootout.py already patched -- skipping.")
else:
    # 3. record_no_shootout(): tag new rows source="auto"; keep the
    #    duplicate-check working whether or not a "source" column exists yet.
    old_record = (
        '    if NO_SHOOTOUT_LOG.exists():\n'
        '        existing = pd.read_csv(NO_SHOOTOUT_LOG)\n'
        '    else:\n'
        '        existing = pd.DataFrame(columns=["date"])\n'
        '\n'
        '    date_str = date_obj.strftime("%Y-%m-%d")\n'
        '    if date_str in existing["date"].astype(str).values:\n'
        '        print(f"{date_str} already recorded as a no-shootout date -- nothing to do.")\n'
        '        return\n'
        '\n'
        '    existing = pd.concat(\n'
        '        [existing, pd.DataFrame([{"date": date_str}])], ignore_index=True\n'
        '    )\n'
        '    existing.to_csv(NO_SHOOTOUT_LOG, index=False)\n'
    )
    new_record = (
        '    if NO_SHOOTOUT_LOG.exists():\n'
        '        existing = pd.read_csv(NO_SHOOTOUT_LOG, dtype=str)\n'
        '    else:\n'
        '        existing = pd.DataFrame(columns=["date", "source"])\n'
        '    if "source" not in existing.columns:\n'
        '        existing["source"] = ""\n'
        '\n'
        '    date_str = date_obj.strftime("%Y-%m-%d")\n'
        '    if date_str in existing["date"].astype(str).values:\n'
        '        print(f"{date_str} already recorded as a no-shootout date -- nothing to do.")\n'
        '        return\n'
        '\n'
        '    # Tagged "auto" (distinct from the admin panel\'s "manual" entries)\n'
        '    # so remove_stale_no_shootout_entry() below only ever removes its\n'
        '    # own kind of entry, never a deliberate manual cancellation.\n'
        '    existing = pd.concat(\n'
        '        [existing, pd.DataFrame([{"date": date_str, "source": "auto"}])], ignore_index=True\n'
        '    )\n'
        '    existing.to_csv(NO_SHOOTOUT_LOG, index=False)\n'
    )
    check = replace_once(check, old_record, new_record, "record_no_shootout")

    # 4. remove_stale_no_shootout_entry(): never remove a "manual" entry.
    old_remove = (
        '    if not NO_SHOOTOUT_LOG.exists():\n'
        '        return\n'
        '    existing = pd.read_csv(NO_SHOOTOUT_LOG)\n'
        '    date_str = date_obj.strftime("%Y-%m-%d")\n'
        '    if date_str not in existing["date"].astype(str).values:\n'
        '        return\n'
        '    existing = existing[existing["date"].astype(str) != date_str]\n'
        '    existing.to_csv(NO_SHOOTOUT_LOG, index=False)\n'
    )
    new_remove = (
        '    if not NO_SHOOTOUT_LOG.exists():\n'
        '        return\n'
        '    existing = pd.read_csv(NO_SHOOTOUT_LOG, dtype=str)\n'
        '    if "source" not in existing.columns:\n'
        '        existing["source"] = ""\n'
        '    date_str = date_obj.strftime("%Y-%m-%d")\n'
        '    row = existing[existing["date"].astype(str) == date_str]\n'
        '    if row.empty:\n'
        '        return\n'
        '    if (row["source"] == "manual").any():\n'
        '        print(f"{date_str} is a manually-recorded no-shootout date -- "\n'
        '              f"leaving it alone (not auto-removing).")\n'
        '        return\n'
        '    existing = existing[existing["date"].astype(str) != date_str]\n'
        '    existing.to_csv(NO_SHOOTOUT_LOG, index=False)\n'
    )
    check = replace_once(check, old_remove, new_remove, "remove_stale_no_shootout_entry")
    check_path.write_text(check, encoding="utf-8")
    print("check_no_shootout.py updated successfully")
