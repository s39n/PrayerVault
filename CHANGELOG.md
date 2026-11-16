# Changelog

## 2026-11-16

- The multi-church application moved to its own project,
  [PrayerVault Church](https://github.com/s39n/PrayerVault-Church). Removed from this
  repo: the church API and pages, the database layer and migrations, email / web-push
  notifications, and the `sqlmodel`, `alembic` and `pywebpush` dependencies. The
  personal journal is unchanged.
- New Prayer leads with the prayer; the title is optional; one "Who is it for?" field.
- Every view has its own address, so Back and refresh behave.

## 2026-11-15

- Fruit page is a vine: fruit for prayers given, pruned branches for answers not as asked.
- Edit and remove prayers (removed notes go to `.trash`); secondary actions under "More".
- Dark mode that follows the device.
- Phones: bottom tab bar; the veil draws back to a thin edge once signed in.
- Fixes: Cancel no longer marks a prayer answered; Back returns where you came from;
  the People tab highlights; Today's wording follows the time of day.
