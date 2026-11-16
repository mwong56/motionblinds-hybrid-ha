# Security

Report credential exposure or security vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/mwong56/motionblinds-hybrid-ha/security/advisories/new).

Keep passwords, account tokens, developer keys, device addresses, and raw traffic
captures out of public issues. Diagnostics omit account credentials and device
identifiers; review any additional logs before sharing them.

Cloud commands use HTTPS with certificate verification. Local status reads use
the gateway's unencrypted UDP protocol. Credentials are stored in Home Assistant's
config entry, while session tokens remain in memory.
