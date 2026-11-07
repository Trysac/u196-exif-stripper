# exif-stripper

[![PyPI version](https://img.shields.io/pypi/v/trysac-exif-stripper)](https://pypi.org/project/trysac-exif-stripper/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-exif-stripper)](LICENSE)
[![CI](https://github.com/Trysac/u196-exif-stripper/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u196-exif-stripper/actions/workflows/ci.yml)

Strip EXIF, GPS, XMP, IPTC and comments from JPEG, PNG and WebP by rewriting container segments byte-exactly, without decoding pixels

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-exif-stripper
# or
uv add trysac-exif-stripper
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import exif_stripper

# normalize() trims surrounding whitespace and lower-cases the text.
print(exif_stripper.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    exif_stripper.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
