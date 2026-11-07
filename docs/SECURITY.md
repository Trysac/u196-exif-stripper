# Security notes

## Threat model

This utility is designed as a library with no runtime dependencies. It does not perform any I/O or network requests. Risks related to untrusted input are mitigated through:

- **Bounds Checking**: `max_bytes` defaults to 100 MB; inputs exceeding this raise an `ExifStripError`.
- **Depth Limits**: The TIFF parser enforces a recursion limit of 10 and a maximum of 1000 IFD entries per block to prevent stack exhaustion or denial of service.
- **Input Sanitization**: Errors are explicit. No `eval` or deserialization (e.g., pickle) is used. Malformed structures result in `ExifStripError` rather than crashing.

## Limits

- JPEG markers are traversed linearly; arbitrary marker nesting is not supported.
- PNG CRC mismatch will raise a `corrupt` error, preventing further processing of potentially compromised files.
- TIFF header parsing returns `(None, False)` upon encountering structural malformations to ensure callers can handle unreadable metadata gracefully without risking exceptions.