# Security policy

## Reporting a vulnerability

Please do **not** open a public issue. Either email **qmgateway@gmail.com**, or use "Report a vulnerability" on the Security tab of the [qmgateway-python](https://github.com/qmgateway-sms/qmgateway-python) repository. Include:

- what you found and which version of the SDK,
- steps to reproduce, and
- anything you think an attacker could do with it.

We acknowledge reports within 3 working days, give you an update at least every 10 working days, and credit you when the fix is released unless you prefer not to be named.

## Supported versions

Only the latest release receives security fixes. After the first `1.0` release, the previous major version gets critical fixes for 6 months after a new major is released.

Supported runtime: Python 3.10 or newer, while that Python release still receives security fixes.

## How we protect releases

- Releases are built and published **only by CI**, with short-lived credentials from the registry's trusted publishing. No registry token is stored anywhere.
- Every account that can publish uses multi-factor authentication.
- Tags are signed and protected. **A published version is never changed or re-tagged.** A mistake gets a new version.
- It has no dependencies of any kind: the SDK and its tests use only the Python standard library. Any dependency we add later is pinned, reviewed and checked by an automated audit on every change.
- The CI workflows use GitHub Actions pinned to full commit hashes, and Dependabot proposes updates.
- No install-time scripts.
- The webhook signature check compares in constant time and rejects requests older than 5 minutes.
- The SDK never follows redirects, so your API key cannot be sent to another host, and it refuses a base address that is not `https` (except `localhost`, for testing).

## Using the SDK safely

- Call QMGateway **from your server**, never from a browser or a mobile app. Anything shipped to a device can be read, including your API key.
- Keep API keys in an environment variable or secret store, never in source control.
- Use a key with only the permissions the job needs, and restrict it to your server's address.
- Verify every webhook before you trust it, using the raw request body.
