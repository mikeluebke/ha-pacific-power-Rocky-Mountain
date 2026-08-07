# Pacific Power Green Button

A [Home Assistant](https://www.home-assistant.io/) custom integration that imports energy usage data from [Pacific Power](https://www.pacificpower.net/) (PacifiCorp) using the Green Button standard.

## Features

- Authenticates with your Pacific Power account via headless browser
- Downloads Green Button (ESPI XML) energy usage data
- Inserts historical consumption data into Home Assistant's long-term statistics
- Works with the HA Energy Dashboard for tracking electricity usage
- Supports forward (consumption) and reverse (solar export) flow directions
- Refreshes automatically every 12 hours

## Prerequisites

This integration uses [Playwright](https://playwright.dev/python/) to automate the Pacific Power portal. Chromium must be installed on your system.

### Home Assistant Container / Supervised / Core

```bash
pip install playwright
playwright install chromium
```

### Home Assistant OS

HA OS does not support installing system-level browser binaries. You will need to run Chromium via a companion Docker container or addon. (Addon coming soon.)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner → **Custom repositories**
3. Add `https://github.com/nkcx/pacific-power-green-button` as an **Integration**
4. Search for "Pacific Power" and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/pacific_power` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Pacific Power**
3. Enter your Pacific Power account email and password
4. Enter your account number (format: `XXXXXXXX-XXX`, found on your bill) and service address

## Energy Dashboard

After the first data fetch (may take a few minutes after setup):

1. Go to **Settings** → **Dashboards** → **Energy**
2. Under **Electricity grid** → **Grid consumption**, click **Add consumption**
3. Select the `pacific_power:...energy_consumption` statistic
4. If you have solar, add the `pacific_power:...energy_returned` statistic under **Return to grid**

## How It Works

Pacific Power's portal encrypts API requests using client-side JavaScript. This integration uses a headless Chromium browser via Playwright to execute the portal's own code, handling authentication and encryption transparently.

The flow:
1. Opens a headless browser and navigates to the Pacific Power portal
2. Fills in your credentials and logs in via Azure AD B2C
3. Executes the portal's JavaScript to make an authenticated, encrypted API call
4. Receives the Green Button (ESPI XML) response
5. Parses the XML and inserts energy data as external statistics in Home Assistant

Data is typically available from Pacific Power with a 24-48 hour delay.

## Troubleshooting

- **Authentication errors**: Verify your Pacific Power credentials at [pacificpower.net](https://www.pacificpower.net/). MFA-enabled accounts are not supported.
- **Browser launch errors**: Ensure Chromium is installed (`playwright install chromium`) and system dependencies are met (`playwright install-deps chromium`).
- **No statistics appearing**: Check the Home Assistant logs for errors. Go to **Developer Tools** → **Statistics** and search for "pacific_power".

## License

MIT
