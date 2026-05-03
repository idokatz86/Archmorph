# Icon-Pack Incident Review

Privileged icon-pack mutation routes emit audit events for upload, replace, delete, validation failures, authorization failures, protected built-in pack deletes, and missing-pack deletes.

## Query

Use the admin audit API and filter for `admin.config_change` events whose `details.operation` is `upload` or `delete` and whose endpoint starts with `/api/icon-packs`.

Each event includes:

- `details.operation`
- `details.outcome`
- `details.pack_id`
- `status_code`
- `correlation_id`
- `user_id` when a valid admin session is available
- backend revision/build metadata when the runtime exposes it

During incident review, pivot from the event `correlation_id` into application logs and compare the event status with the response envelope returned to the caller. Audit failures are non-blocking and should appear only as debug logs.
