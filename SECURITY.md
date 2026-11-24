# Privacy and credential handling

The repository MUST exclude personal email addresses, passwords, AWS keys,
tokens, real robot identifiers and names, maps, and captures. Password hashes,
user certificates, topics containing identifiers, and complete state documents
are also private.

Pass the paths to private files to the tools. Keep credentials out of command
line arguments. Store the files outside the checkout with mode `0600` and their
directory with mode `0700`. Keep them out of issues, pull requests, and logs.
The library redacts sensitive objects and omits response bodies, authentication
headers, and credentials from output.

The ignore rules exclude common private capture locations and key files.
Review the actual contents of new files and run
`python3 scripts/check_privacy.py` before committing. This script checks common
patterns and can miss secrets in arbitrary files.

HTTP requires validated TLS, disables redirects, and checks discovered domains
before sending account data or signing requests. MQTT uses the IoT host,
device-scoped tokens, and exact topic subscriptions. Public reports contain
counts, normalized routes, and classifications.

Limit Proxyman and its root certificate to the authorized research emulator.
Treat decrypted captures as live sessions. During the initial investigation the
local VPN disrupted sign-in, so the native HTTP capture used the emulator proxy
with the VPN stopped. Keep TLS verification enabled in the integration client.

After a test campaign, replace the temporary password and revoke the test
sessions where the provider allows it. Keep the necessary private evidence
until verification is complete and then remove the login files and captures
that are no longer needed.

Report issues with a description and a synthetic example. Keep original
provider responses private.
