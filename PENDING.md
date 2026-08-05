# Pending work

## Fix localized WhatsApp export parsing after end-to-end test

- Support Spanish WhatsApp timestamps containing `a. m.` / `p. m.`.
- Accept Unicode non-breaking spaces (`U+00A0`, `U+202F`) around meridiem markers.
- Update both automatic adapter detection and `chat_export` timestamp parsing.
- Preserve multiline WhatsApp messages instead of treating continuation lines separately or dropping them.
- Add Spanish entity and relationship extraction; current KG phrase patterns are English-only.
- Add regression fixtures and tests for localized Android/iOS WhatsApp exports on Windows.
- Remove need for temporary UTF-8 normalization workaround.

Current workaround: read export explicitly as UTF-8, normalize Unicode spaces and localized meridiem markers, then force `--adapter chat_export`.
