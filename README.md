# PetTec (Snoop Cube) — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for the [PetTec Cam Buddy](https://pettec.de/products/pettec-cam-buddy-inkl-futterautomat)
pet feeder, exposing a **"Feed one portion"** button you can press from the dashboard
or trigger from any automation.

The integration talks to PetTec's cloud (the same backend the **Snoop Cube** mobile app
uses — operated by [Meari](https://www.meari.com.cn/) under the CloudEdge brand).

## Status

- ✅ Cam Buddy: feed one portion — works
- 🟦 Other PetTec / Snoop Cube cameras: discovered automatically, but no controls yet

## Features

- Single config flow (email + password)
- Automatic discovery of all feeders on the account
- One button entity per feeder
- Multi-region: works with EU and global Meari endpoints
- Auto-retry if the cloud invalidates a session

## Installation

### Via HACS (custom repository)

1. In HACS → **Integrations** → top-right ⋮ menu → **Custom repositories**.
2. Add `https://github.com/woorari/pettec-home-assistant` as **Integration**.
3. Find **PetTec (Snoop Cube)** in the HACS integrations list and install it.
4. **Restart Home Assistant.**
5. **Settings → Devices & Services → Add Integration → "PetTec (Snoop Cube)"**.

### Manual

1. Copy `custom_components/pettec/` into your HA config's `custom_components/` directory.
2. Restart HA.
3. Add the integration via the UI.

## Configuration

The config flow asks for:

| Field | Required | Default | Notes |
|---|---|---|---|
| Email | yes | – | Snoop Cube account email |
| Password | yes | – | Snoop Cube account password |
| Country code | no | `DE` | ISO 3166-1 alpha-2, used during login |
| Phone code | no | `49` | Country dialing code, used during login |

> **Strongly recommended:** create a dedicated Snoop Cube account (e.g. `home-assistant@yourdomain`)
> and use the app's "share device" feature to grant it access to your feeder. Meari
> allows only one active session per account, so if HA and your phone share an
> account, every login from one bumps the other.

## Entities

For each discovered feeder you'll get:

- **`button.<device_name>_feed_one_portion`** — pressing it tells the feeder to dispense
  one portion. The portion size is whatever you set in the Snoop Cube app for "manual feed".

## Use in automations

```yaml
# Feed once at 8 AM and 6 PM
alias: Cat schedule
triggers:
  - trigger: time
    at: "08:00"
  - trigger: time
    at: "18:00"
actions:
  - action: button.press
    target:
      entity_id: button.pet_cam_buddy_feed_one_portion
```

## How it works

The Snoop Cube app authenticates against `apis.cloudedge360.com` (or a regional
mirror like `apis-eu-frankfurt.cloudedge360.com`), receives a `userToken` and
`pfKey` (per-tenant access credentials), then issues feeder commands as IoT
property writes against `openapi-<region>.mearicloud.com/openapi/device/config`.

The "feed one portion" command is IoT property `850` (petFeed2) with payload
`{"parts": 1}`. See [`meari_api.py`](custom_components/pettec/meari_api.py) for the full implementation.

## Limitations

- The Meari cloud allows only **one active session per account**. If you (or your
  phone) log in to the same account, HA's session is invalidated. Use a dedicated
  shared account for HA.
- This integration uses cloud APIs only — it does not stream video, query SD card
  recording, control PTZ, or read sensor values. Those features are technically
  feasible but out of scope for v0.1.
- This integration is not affiliated with PetTec or Meari.

## Troubleshooting

Enable debug logging by adding to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.pettec: debug
```

Restart HA, reproduce the problem, then share the relevant log lines.

## Contributing

Issues and PRs welcome. The code is intentionally small and well-commented.

## License

[MIT](LICENSE)
