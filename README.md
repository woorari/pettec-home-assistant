# PetTec (Snoop Cube) — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for the [PetTec Cam Buddy](https://pettec.de/products/pettec-cam-buddy-inkl-futterautomat)
feeder and the rest of the **Snoop Cube** camera lineup (Cam Free, Cam Lite, Cam 360, etc).

The integration talks to PetTec's cloud (the same backend the **Snoop Cube** mobile app
uses — operated by [Meari](https://www.meari.com.cn/) under the CloudEdge brand).

## Status

- ✅ Pet Cam Buddy — feed control, full state visibility, all detection toggles
- ✅ All other PetTec cameras — on/off, recording, motion/human/sound/PIR/cry detection, sensitivity sliders, SD card sensors, Wi-Fi, battery, firmware
- 🟦 Live video / playback / schedule editing — not yet (v0.3+)

## Features

- Single config flow (email + password)
- Automatic discovery of all cameras + feeders on the account, including shared (`asFriend`) devices
- Up to **20+ entities per device**: switch / number / sensor / binary_sensor / button
- Hourly cloud polling (configurable in code) — sufficient since feeder/camera state changes are infrequent
- Transparent **wake-on-write** for dormant battery cameras
- Multi-region: works with EU, US, and China Meari endpoints (auto-detected from login)
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

Per discovered device (some are conditional — battery sensors only on battery
cams, pet alarm only on the feeder, etc.):

| Type | Entity | Notes |
|---|---|---|
| **button** | `feed_one_portion` | Cam Buddy only — dispenses one portion |
| **switch** | `active` | Camera on/off (sleepMode) |
| **switch** | `recording` | SD-card recording on/off |
| **switch** | `motion_detection` | Motion alerts on/off |
| **switch** | `human_detection` | Human-shape alerts |
| **switch** | `sound_detection` | Sound alerts |
| **switch** | `cry_detection` | Cry/whining alerts |
| **switch** | `human_tracking` | Auto-follow (PTZ cams only) |
| **switch** | `pir_detection` | PIR sensor (battery cams only) |
| **switch** | `pet_alarm` | Feeder bowl-tip alarm enable |
| **switch** | `pet_meow` | Pet sound mode (feeder) |
| **number** | `motion_sensitivity` / `sound_sensitivity` / `pir_sensitivity` | 0–10 sliders |
| **sensor** | `battery` | Battery cams: % |
| **sensor** | `wifi_strength` | Signal % |
| **sensor** | `firmware_version` | Diagnostic |
| **sensor** | `sd_card_status` / `sd_card_capacity` / `sd_card_remaining` | SD card |
| **sensor** | `today_feed_count` / `next_feed_time` / `food_out_minutes` / `desiccant_info` | Feeder only |
| **binary_sensor** | `charging` | Battery cams only |
| **binary_sensor** | `food_empty` / `desiccant_expired` / `pet_throw_warning` | Feeder only |

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

```yaml
# Disable cameras when "home" mode is active
alias: Privacy when home
triggers:
  - trigger: state
    entity_id: input_boolean.away_mode
    to: "off"
actions:
  - action: switch.turn_off
    target:
      entity_id:
        - switch.wohnzimmer_cam_active
        - switch.schlafzimmer_cam_active
```

## How it works

Authentication: 3DES password + HMAC-SHA1 signed body params against
`apis.cloudedge360.com` → returns `userToken` + `pfKey` (per-tenant access
credentials). Subsequent calls hit a regional mirror auto-detected from
the login response.

State reads use `/v2/app/iot/model/get/batch` — a single batch call covers
all devices, including dormant battery cams (which return cached state).
State writes go to `/openapi/device/config?action=set`. Battery cams in
`dormancy` are transparently woken via `/openapi/device/awaken` before
writes.

Feed: IoT property `850` (petFeed2) with payload `{"parts": 1}`.
Camera on/off: IoT property `118` (sleepMode) — note the inversion, value 0
means "active". See [`meari_api.py`](custom_components/pettec/meari_api.py)
for the full reference.

## Limitations

- The Meari cloud allows only **one active session per account**. If you (or your
  phone) log in to the same account, HA's session is invalidated. Use a dedicated
  shared account for HA.
- Cloud-only — no live video, no playback browsing, no schedule editing yet.
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
