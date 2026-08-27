"""Constants for the Pacific Power / Rocky Mountain Power integration."""
from typing import Final

DOMAIN: Final = "pacific_power"

CONF_CUSTOMER_IDN = "customer_idn"
CONF_ACCOUNT_SEQUENCE = "account_sequence"
CONF_AGREEMENT_SEQUENCE = "agreement_sequence"
CONF_SERVICE_ADDRESS = "service_address"
CONF_TIMEZONE = "timezone"

# Utility Brand Options
CONF_UTILITY = "utility"
UTILITY_PACIFIC_POWER = "pacific_power"
UTILITY_ROCKY_MOUNTAIN = "rocky_mountain_power"

UTILITY_DOMAINS = {
    UTILITY_PACIFIC_POWER: {
        "name": "Pacific Power",
        "base_url": "https://csapps.pacificpower.net",
        "login_url": "https://login.csapps.pacificpower.net",
        "subsidiary": "PacificPower",
    },
    UTILITY_ROCKY_MOUNTAIN: {
        "name": "Rocky Mountain Power",
        "base_url": "https://csapps.rockymountainpower.net",
        "login_url": "https://login.csapps.rockymountainpower.net",
        "subsidiary": "RockyMountainPower",
    },
}

# Defaults (Fallback to Pacific Power if unspecified)
BASE_URL = UTILITY_DOMAINS[UTILITY_PACIFIC_POWER]["base_url"]
B2C_LOGIN_URL = UTILITY_DOMAINS[UTILITY_PACIFIC_POWER]["login_url"]
PACIFICORP_SUBSIDIARY = UTILITY_DOMAINS[UTILITY_PACIFIC_POWER]["subsidiary"]
