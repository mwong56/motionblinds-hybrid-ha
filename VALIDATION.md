# Validation

The functional implementation was tested with a CMD-01 gateway, six bidirectional
blinds, and Home Assistant Core 2026.11.1. These results do not establish support
for other gateways, regions, or motor variants.

## Automated checks

- **27 tests pass** on Python 3.14 and Core 2026.11.1; Ruff checks pass.
- HA tests cover configuration, entity registration, command routing, local updates, options/reload, reauthentication, metadata renames, and unload cleanup.
- Protocol tests use a loopback HTTP server to check identity matching, token refresh, timeout behavior, command validation, and sanitized errors.
- A public Java-generated fixture independently checks password preprocessing.

## Live checks

- Cloud login and token refresh succeeded, with stable metadata identities.
- Cloud and local status matched across all nine fields for all six blinds.
- Six covers and 18 sensors loaded and reported again through regular local polling.
- Percentage movement on one blind reached both requested positions; local and cloud readings agreed afterward.
- An HA service request reached the cloud, and diagnostics passed a credential scan.

## Limits

- Only one blind's actual movement was exercised. Other blinds' reads were validated.
- Local reads use gateway-held values. They followed observed movements but do not force a new radio report on each poll.
- Battery indicators estimate charge from voltage. Different conversion methods can produce different percentages from the same reading.
- The integration works around local command authentication failure; it does not modify or repair firmware.
