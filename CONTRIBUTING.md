# Contributing

Bug reports, ideas, documentation improvements, and Pull Requests are welcome.
For bugs, include your macOS version, app version, steps to reproduce, and expected behavior.
Include your Python version when running from source.

## License of contributions

Unless a separately licensed component is explicitly identified, contributions are submitted
under the project's **GPL-3.0-only** license. Submit only material you have the right to
contribute under those terms. Keep existing author and license notices, and identify any
third-party material and its original license. The puzzle data retains its separate
public-domain dedication.

You retain copyright in your contributions. Add accurate notices for substantial original
contributions as appropriate; do not replace another author's credit with your own. No
additional copyright assignment is requested.

See [LICENSE](LICENSE) and the [licensing guide](docs/licensing.md) for details.

## Development

Follow the existing Python style: meaningful names, focused functions, type annotations,
clear docstrings, and consistent formatting. Include focused regression coverage for behavior
changes. Run the checks in the [development guide](docs/development.md#checks).
See [automatic versioning](docs/development.md#automatic-versioning) before committing maintainer
changes; feature additions and PR fixes use different version increments.

For dependency or packaging changes, review and refresh the upstream notices and provenance
inventory as described in the [licensing guide](docs/licensing.md#dependency-and-notice-maintenance).
Do not assume that a successful build means a binary is ready for public distribution.
