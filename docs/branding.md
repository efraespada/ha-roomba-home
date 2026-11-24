# Integration icon

The integration uses the Roomba Home iOS icon supplied by the account owner.
The conversion preserves the original design, colors, corners, and
transparency, and strips file metadata.

| Distributed file | Format | Dimensions |
|---|---|---|
| `custom_components/roomba_home/brand/icon.png` | Interlaced RGBA PNG | 256×256 |
| `custom_components/roomba_home/brand/icon@2x.png` | Interlaced RGBA PNG | 512×512 |

Each output was resized directly from the 400×400 WebP. The 512-pixel variant
uses Lanczos upscaling and adds no generated detail. Both retain transparency.

The project follows My Verisure's packaging and Home Assistant's local
`brand/` convention, available since Home Assistant 2026.3. The validated
version is 2026.11.2. The square icon doubles as a logo. Home Assistant's
theme fallback uses the same image for light and dark themes.
[My Verisure branding](https://github.com/efraespada/my_verisure/tree/master/custom_components/my_verisure/brand) ·
[Home Assistant brands](https://contributors.home-assistant.io/core/integrations/brands/)

The local checks verify PNG format, dimensions, alpha, and absence of
metadata. The privacy scanner allowlists the two verified paths by exact
SHA-256 digest. Modified binaries require review. Home Assistant Green
showed the local icon after the 0.3.0 upgrade. An isolated test served both
sizes and their dark-theme fallbacks through the Home Assistant brands endpoint.
[Upgrade validation](validation.md)

[Third-party notices](../THIRD_PARTY_NOTICES.md)
