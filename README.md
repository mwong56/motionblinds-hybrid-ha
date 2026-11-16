# Motionblinds Hybrid

A Home Assistant custom integration for Motionblinds CMD-01 gateways. It sends
commands through the cloud, reads status locally, and uses cloud names matched
to device IDs.

This provides a workaround for gateways that reject authenticated local commands
while still answering local status reads. It uses an unofficial API and is not
affiliated with Motionblinds or Coulisse.

## Features

- Open, close, stop, and set the opening percentage.
- Read position, battery voltage, battery estimates, and signal strength locally.
- Import cloud names by device ID, so names do not depend on discovery order.
- Keep reading local status during cloud outages using cached metadata.
- Refresh expired cloud sessions and offer reauthentication when needed.

## Requirements

- Home Assistant **2026.11 or later**.
- A **CMD-01** gateway reachable from Home Assistant over UDP port **32100**.
- A Motionblinds **Bridge** app account using the **EU cloud service**.
- Bidirectional blinds registered to that gateway, reported as device type `10000000`.

Other gateways, regions, and motor types have not been validated. See
[validation](VALIDATION.md) for the tested scope.

## Install

**With HACS:** add `https://github.com/mwong56/motionblinds-hybrid-ha` as a custom
repository of type **Integration**, download Motionblinds Hybrid, and restart
Home Assistant. See [HACS custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).

**Manually:** copy `custom_components/motionblinds_hybrid` into Home Assistant's
`/config/custom_components/` folder, then restart Home Assistant.

1. Open **Settings → Devices & services → Add integration → Motionblinds Hybrid**.
2. Enter your Bridge app email, password, and gateway address.
3. Check the imported names and readings, then disable the stock Motionblinds entry if you previously used it.

Setup needs both cloud access and a reachable local gateway. Existing entity
names can cause numeric suffixes; match devices by ID before changing automations.

## How it works

- **Commands:** cloud requests control the blinds. An accepted request does not immediately change the displayed position; local readings confirm it.
- **Status:** the gateway cache is polled every 30 seconds. After a command, local reads run every two seconds for up to a minute.
- **Names:** cloud metadata refreshes hourly. Existing device identities and user-assigned HA names are preserved.
- **Failures:** cloud outages leave local reads working. Failed local reads make the affected entities unavailable. Movement requests are not retried after an uncertain delivery timeout.

Use **Configure** to change the gateway address, polling interval, or battery
calculation. The address must still identify the same gateway.

## Battery readings

Battery percentages are estimates derived from voltage, not measured charge.

- **HA voltage estimate:** provides finer percentages. Choose this for the dashboard example.
- **App indicator:** the default stepped indicator uses 0%, 10%, 20%, 50%, and 100%. Its 100% band does not establish a full charge.
- **Battery voltage:** exposes the underlying reading so you can compare estimates.

The [dashboard example](examples/blinds-card.yaml) includes cover controls,
position sliders, and a compact estimate/voltage table. Replace its sample entity
IDs with your own. No custom frontend cards are required.

## Development

Use Python 3.14, install `requirements-dev.txt` in a virtual environment, and run
`python -m pytest -q` followed by `ruff check custom_components tests`.
Tests use synthetic data and a loopback HTTP server; no account is needed.

See [progress](PROGRESS.md), [validation](VALIDATION.md), and
[security reporting](SECURITY.md). Contributions and bug reports are welcome;
include the HA version and redacted diagnostics when useful.

## Uninstall

Remove the integration in **Devices & services**, delete
`/config/custom_components/motionblinds_hybrid`, and restart Home Assistant.
You can add the stock Motionblinds integration again, but this will not fix the
gateway's original local authentication problem.
