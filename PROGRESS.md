# Progress

The first release implements cloud control with local status and cloud-provided
names. Personal deployment notes and captures are kept outside the public history.

## Completed

- **Protocol client:** cloud login, refresh, commands, and local cache reads.
- **Identity mapping:** match cloud metadata to locally advertised device IDs.
- **HA integration:** config flow, covers, sensors, options, reauthentication, and diagnostics.
- **Failure handling:** isolate cloud outages from local reads, mark failed local devices unavailable, and avoid retrying commands after uncertain timeouts.
- **Dashboard example:** native cover controls, position sliders, and estimated battery percentages alongside voltage.
- **Validation:** 27 automated tests, lint checks, and live CMD-01 checks. See [validation](VALIDATION.md).
- **Public preparation:** generic examples, concise documentation, credential checks, and a clean release history.

## Not yet validated

- Gateways and cloud regions beyond CMD-01 and the EU service.
- Movement across every motor variant.
- Firmware repair or authenticated local control.
