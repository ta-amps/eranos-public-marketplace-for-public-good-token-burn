# Volunteer sign-up sheet cleaning report

This report holds counts only, never rows from your files.

Files read: 4. Flags for a person: 11. Changes recorded: 44.

| What | empty-sheet-sample.csv | fall-fair-signups-sample.tsv | spring-signups-sample.csv | winter-signups-sample.csv | Total |
|---|---|---|---|---|---|
| Rows read | 0 | 6 | 14 | 3 | 23 |
| Rows in the cleaned copy | 0 | 5 | 11 | 3 | 19 |
| Duplicates removed | 0 | 1 | 3 | 0 | 4 |
| Possible duplicates for a person | 0 | 0 | 1 | 0 | 1 |
| Duplicate details that disagree | 0 | 0 | 1 | 0 | 1 |
| Dates put in YYYY-MM-DD form | 0 | 6 | 11 | 3 | 20 |
| Dates that could be read two ways | 0 | 0 | 0 | 2 | 2 |
| Dates the process could not read | 0 | 0 | 2 | 0 | 2 |
| Phone numbers put in +country form | 0 | 4 | 11 | 2 | 17 |
| Phone numbers the process could not read | 0 | 0 | 1 | 0 | 1 |
| Email addresses trimmed or lowercased | 0 | 1 | 1 | 0 | 2 |
| Email addresses the process could not read | 0 | 1 | 1 | 0 | 2 |
| Rows with no email and no phone | 0 | 0 | 1 | 0 | 1 |
| Rows missing a required field | 0 | 0 | 1 | 0 | 1 |

## What a person checks

- 2 x `ambiguous_date`: see flags.csv rows with needs_person = yes.
- 1 x `duplicate_conflict`: see flags.csv rows with needs_person = yes.
- 2 x `invalid_date`: see flags.csv rows with needs_person = yes.
- 2 x `invalid_email`: see flags.csv rows with needs_person = yes.
- 1 x `invalid_phone`: see flags.csv rows with needs_person = yes.
- 1 x `missing_contact`: see flags.csv rows with needs_person = yes.
- 1 x `missing_required`: see flags.csv rows with needs_person = yes.
- 1 x `possible_duplicate`: see flags.csv rows with needs_person = yes.

## Summary

The process read 23 rows in 4 file(s) and kept 19, removing 4 duplicates. It put 20 dates and 17 phone numbers in one format. 11 flags need a person, including 1 row(s) with no email and no phone.

Summary written by: the process's fixed template (no model).

The input files were read and never changed. Nothing was sent anywhere.
