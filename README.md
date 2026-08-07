# Pacific Power for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration that imports daily energy usage data from [Pacific Power](https://www.pacificpower.net/) (PacifiCorp) into the HA Energy Dashboard.

## Features

- Automatic login and data fetch — no manual downloads
- Daily kWh consumption data inserted into HA long-term statistics
- Works with the Energy Dashboard out of the box
- Auto-discovers accounts and metered agreements during setup
- Refreshes every 12 hours
- Pure Python — no browser or external service dependencies

## How It Works

Pacific Power's web portal encrypts all API traffic using RSA signatures and AES-256-GCM encryption. This integration reverse-engineers that protocol:

1. Authenticates via Azure AD B2C (Pacific Power's login provider)
2. Performs an RSA-4096 key exchange with the portal's `/idm/handshake` endpoint
3. Makes encrypted, signed API calls to fetch daily energy usage data
4. Inserts the data as external statistics in Home Assistant's recorder

## Installation

### HACS (Recommended)

1. Open HACS → **Custom repositories**
2. Add `https://github.com/nkcx/ha-pacific-power` as an **Integration**
3. Search for "Pacific Power" and install
4. Restart Home Assistant

### Manual

Copy `custom_components/pacific_power` to your HA `custom_components` folder and restart.

## Setup

1. **Settings** → **Devices & Services** → **Add Integration** → **Pacific Power**
2. Enter your Pacific Power username and password
3. Your account is auto-discovered — select it if you have multiple

## Energy Dashboard

After the first data fetch:

1. **Settings** → **Dashboards** → **Energy**
2. **Grid consumption** → **Add consumption**
3. Select the `pacific_power:...energy_consumption` statistic

## Requirements

- A Pacific Power (PacifiCorp) account with online access
- MFA must be disabled on the account
- `cryptography` Python package (installed automatically)

## License

MIT
