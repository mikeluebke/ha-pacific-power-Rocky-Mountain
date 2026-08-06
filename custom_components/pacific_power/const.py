"""Constants for the Pacific Power integration."""

DOMAIN = "pacific_power"

CONF_CUSTOMER_IDN = "customer_idn"
CONF_ACCOUNT_SEQUENCE = "account_sequence"
CONF_AGREEMENT_SEQUENCE = "agreement_sequence"
CONF_SERVICE_ADDRESS = "service_address"

BASE_URL = "https://csapps.pacificpower.net"
B2C_TENANT = "bheb2c.onmicrosoft.com"
B2C_POLICY = "B2C_1A_PAC_SIGNIN"
B2C_CLIENT_ID = "8e1814e4-56fa-4812-9392-6096657026e7"
B2C_LOGIN_URL = f"https://login.csapps.pacificpower.net/{B2C_TENANT}"
B2C_AUTH_URL = f"{B2C_LOGIN_URL}/{B2C_POLICY.lower()}/oauth2/v2.0/authorize"
B2C_TOKEN_URL = f"{B2C_LOGIN_URL}/{B2C_POLICY.lower()}/oauth2/v2.0/token"

OAUTH_INIT_PATH = f"/oauth2/authorization/{B2C_POLICY}"
GREEN_BUTTON_PATH = "/secure/energy-usage/getGreenButtonData"

DEFAULT_MONTHS = 12
