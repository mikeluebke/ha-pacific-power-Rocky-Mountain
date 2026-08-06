# Pacific Power Green Button

A [Home Assistant](https://www.home-assistant.io/) custom integration that imports energy usage data from [Pacific Power](https://www.pacificpower.net/) (PacifiCorp) using the Green Button standard.

## Features

- Authenticates with your Pacific Power account
- Downloads Green Button (ESPI XML) energy usage data
- Inserts historical consumption data into Home Assistant's long-term statistics
- Works with the HA Energy Dashboard for tracking electricity usage
- Supports forward (consumption) and reverse (solar export) flow directions
- Refreshes automatically every 12 hours

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
4. The integration will auto-discover your account details

## Energy Dashboard

After the first data fetch (may take a few minutes after setup):

1. Go to **Settings** → **Dashboards** → **Energy**
2. Under **Electricity grid** → **Grid consumption**, click **Add consumption**
3. Select the `pacific_power:...energy_consumption` statistic
4. If you have solar, add the `pacific_power:...energy_returned` statistic under **Return to grid**

## How It Works

Pacific Power provides energy usage data via the [Green Button](https://www.energy.gov/data/green-button) standard (ESPI XML format). This integration:

1. Logs into your Pacific Power account via their web portal
2. Downloads your Green Button usage data (daily kWh readings)
3. Parses the ESPI XML and converts readings to kWh
4. Inserts the data as external statistics in Home Assistant's recorder

Data is typically available with a 24-48 hour delay from Pacific Power.

## Troubleshooting

- **Authentication errors**: Verify your Pacific Power credentials at [pacificpower.net](https://www.pacificpower.net/). The integration does not support MFA-enabled accounts.
- **No statistics appearing**: Check the Home Assistant logs for errors. Go to **Developer Tools** → **Statistics** and search for "pacific_power".
- **Account details not found**: If auto-discovery fails, you'll be prompted to enter your account details manually. Find them in your browser's developer tools on the Pacific Power energy usage page.

## License

MIT
