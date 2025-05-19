# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import argparse
import logging
import time
from datetime import datetime

import requests
from selenium import webdriver

LOG = logging.getLogger(__name__)
log_formatter = logging.Formatter(
    "%(asctime)s - %(process)s - %(levelname)s - %(message)s"
)
sh = logging.StreamHandler()
sh.setFormatter(log_formatter)
LOG.addHandler(sh)


def parse_arguments():
    """
    Parse and validate command-line arguments for the cart renewal system.

    Returns:
        argparse.Namespace: Object containing parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Recreation.gov cart renewal automation script"
    )

    # Required arguments
    parser.add_argument(
        "--bot-token", required=True, help="Telegram bot token for notifications"
    )
    parser.add_argument(
        "--chat-id", required=True, help="Telegram chat ID for notifications"
    )
    parser.add_argument(
        "--selenium-host",
        required=True,
        help="Selenium host address for web automation",
    )
    parser.add_argument(
        "--username", required=True, help="Username for Recreation.gov authentication"
    )
    parser.add_argument(
        "--password", required=True, help="Password for Recreation.gov authentication"
    )

    # Optional arguments
    parser.add_argument(
        "--selenium-port",
        type=int,
        default=4444,
        help="Selenium server port (default: 4444)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode for verbose logging"
    )

    args = parser.parse_args()
    return args


def create_selenium_driver(selenium_host, selenium_port):
    """
    Creates and returns a Selenium WebDriver instance connected to a remote Selenium server.

    Args:
        selenium_host (str): The hostname or IP address of the Selenium server.
        selenium_port (int or str): The port number on which the Selenium server is running.

    Returns:
        selenium.webdriver.Remote or None: A Selenium WebDriver instance if the connection is successful;
        otherwise, None if the server is unreachable or driver initialization fails.

    Raises:
        None. All exceptions are caught and handled within the function.

    Notes:
        - The function checks the Selenium server status before attempting to create the driver.
        - Chrome browser options are configured to disable GPU and start in fullscreen mode.
        - Uncomment the '--headless' argument to run Chrome in headless mode.
    """
    # Correctly construct the Selenium WebDriver URL
    selenium_url = f"http://{selenium_host}:{selenium_port}/wd/hub"
    LOG.debug(f"Selenium URL: {selenium_url}")

    # Validate the Selenium server connection
    try:
        response = requests.get(f"http://{selenium_host}:{selenium_port}/status")
        if response.status_code != 200:
            LOG.info("Selenium server is not running or not reachable.")
            return None
    except requests.exceptions.RequestException as e:
        LOG.debug(f"Error connecting to Selenium server: {e}")
        return None

    # Create the Selenium WebDriver instance
    chrome_options = webdriver.ChromeOptions()
    # chrome_options.add_argument('--headless')
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--start-fullscreen")
    try:
        driver = webdriver.Remote(command_executor=selenium_url, options=chrome_options)
        return driver
    except Exception as e:
        LOG.debug(f"Error initializing Selenium WebDriver: {e}")
        return None


def main(args):
    """
    Main function to renew the cart.

    Args:
        args: Parsed command-line arguments
    """
    # Create Selenium WebDriver instance
    # Get the Selenium host and port from command line arguments
    selenium_host = args.selenium_host
    selenium_port = args.selenium_port if args.selenium_port else 4444

    driver = create_selenium_driver(selenium_host, selenium_port)
    if driver:
        LOG.info("Selenium WebDriver instance created successfully.")
        # Perform cart renewal logic here

        driver.get("https://fast.com/")
        time.sleep(5)

        # Close the driver after use
        driver.quit()
        LOG.info("Selenium WebDriver instance closed.")
    else:
        LOG.info("Failed to create Selenium WebDriver instance.")

    return


if __name__ == "__main__":
    args = parse_arguments()

    if args.debug:
        LOG.setLevel(logging.DEBUG)

    LOG.info("-" * 80)
    LOG.info(args)

    main(args)
