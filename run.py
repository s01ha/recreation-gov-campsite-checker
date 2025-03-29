# -*- coding: utf-8 -*-
#!/usr/bin/env python3

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import count, groupby

from dateutil import rrule
import urllib

from clients.recreation_client import RecreationClient
from enums.date_format import DateFormat
from enums.emoji import Emoji
from utils import formatter
from utils.camping_argparser import CampingArgumentParser
import os
import requests
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

LOG = logging.getLogger(__name__)
log_formatter = logging.Formatter(
    "%(asctime)s - %(process)s - %(levelname)s - %(message)s"
)
sh = logging.StreamHandler()
sh.setFormatter(log_formatter)
LOG.addHandler(sh)


def get_park_information(
    park_id, start_date, end_date, campsite_type=None, campsite_ids=(), excluded_site_ids=[]
):
    """
    This function consumes the user intent, collects the necessary information
    from the recreation.gov API, and then presents it in a nice format for the
    rest of the program to work with. If the API changes in the future, this is
    the only function you should need to change.

    The only API to get availability information is the `month?` query param
    on the availability endpoint. You must query with the first of the month.
    This means if `start_date` and `end_date` cross a month boundary, we must
    hit the endpoint multiple times.

    The output of this function looks like this:

    {"<campsite_id>": [<date>, <date>]}

    Where the values are a list of ISO 8601 date strings representing dates
    where the campsite is available.

    Notably, the output doesn't tell you which sites are available. The rest of
    the script doesn't need to know this to determine whether sites are available.
    """

    # Get each first of the month for months in the range we care about.
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(
        rrule.rrule(rrule.MONTHLY, dtstart=start_of_month, until=end_date)
    )

    # Get data for each month.
    api_data = []
    for month_date in months:
        api_data.append(RecreationClient.get_availability(park_id, month_date))

    # Collapse the data into the described output format.
    # Filter by campsite_type if necessary.
    data = {}

    for month_data in api_data:
        for campsite_id, campsite_data in month_data["campsites"].items():
            if campsite_id in excluded_site_ids:
                continue
            available = []
            a = data.setdefault(campsite_id, [])
            for date, availability_value in campsite_data[
                "availabilities"
            ].items():
                if availability_value != "Available":
                    continue

                if (
                    campsite_type
                    and campsite_type != campsite_data["campsite_type"]
                ):
                    continue

                if (
                    len(campsite_ids) > 0
                    and int(campsite_data["campsite_id"]) not in campsite_ids
                ):
                    continue

                available.append(date)
            if available:
                a += available

    return data

def is_weekend(date):
    weekday = date.weekday()

    return weekday == 4 or weekday == 5


def get_num_available_sites(
    park_information, start_date, end_date, nights=None, weekends_only=False,
):
    maximum = len(park_information)

    num_available = 0
    num_days = (end_date - start_date).days
    dates = [end_date - timedelta(days=i) for i in range(1, num_days + 1)]
    if weekends_only:
        dates = filter(is_weekend, dates)
    dates = set(
        formatter.format_date(
            i, format_string=DateFormat.ISO_DATE_FORMAT_RESPONSE.value
        )
        for i in dates
    )

    if nights not in range(1, num_days + 1):
        nights = num_days
        LOG.debug("Setting number of nights to {}.".format(nights))

    available_dates_by_campsite_id = defaultdict(list)
    for site, availabilities in park_information.items():
        # List of dates that are in the desired range for this site.
        desired_available = []

        for date in availabilities:
            if date not in dates:
                continue
            desired_available.append(date)

        if not desired_available:
            continue

        appropriate_consecutive_ranges = consecutive_nights(
            desired_available, nights
        )

        if appropriate_consecutive_ranges:
            num_available += 1
            LOG.debug("Available site {}: {}".format(num_available, site))

        for r in appropriate_consecutive_ranges:
            start, end = r
            available_dates_by_campsite_id[int(site)].append(
                {"start": start, "end": end}
            )

    return num_available, maximum, available_dates_by_campsite_id


def consecutive_nights(available, nights):
    """
    Returns a list of dates from which you can start that have
    enough consecutive nights.

    If there is one or more entries in this list, there is at least one
    date range for this site that is available.
    """
    ordinal_dates = [
        datetime.strptime(
            dstr, DateFormat.ISO_DATE_FORMAT_RESPONSE.value
        ).toordinal()
        for dstr in available
    ]
    c = count()

    consecutive_ranges = list(
        list(g) for _, g in groupby(ordinal_dates, lambda x: x - next(c))
    )

    long_enough_consecutive_ranges = []
    for r in consecutive_ranges:
        # Skip ranges that are too short.
        if len(r) < nights:
            continue
        for start_index in range(0, len(r) - nights + 1):
            start_nice = formatter.format_date(
                datetime.fromordinal(r[start_index]),
                format_string=DateFormat.INPUT_DATE_FORMAT.value,
            )
            end_nice = formatter.format_date(
                datetime.fromordinal(r[start_index + nights - 1] + 1),
                format_string=DateFormat.INPUT_DATE_FORMAT.value,
            )
            long_enough_consecutive_ranges.append((start_nice, end_nice))

    return long_enough_consecutive_ranges


def check_park(
    park_id, start_date, end_date, campsite_type, campsite_ids=(), nights=None, weekends_only=False, excluded_site_ids=[],
):
    park_information = get_park_information(
        park_id, start_date, end_date, campsite_type, campsite_ids, excluded_site_ids=excluded_site_ids,
    )
    LOG.debug(
        "Information for park {}: {}".format(
            park_id, json.dumps(park_information, indent=2)
        )
    )
    park_name = RecreationClient.get_park_name(park_id)
    current, maximum, availabilities_filtered = get_num_available_sites(
        park_information, start_date, end_date, nights=nights, weekends_only=weekends_only,
    )
    return current, maximum, availabilities_filtered, park_name


def merge_consecutive_dates(dates):
    """
    Merge consecutive date ranges.

    Args:
        dates (list of dict): List of date ranges with 'start' and 'end' keys.

    Returns:
        list of dict: Merged list of date ranges.
    """
    if not dates:
        return []

    # Convert date strings to datetime objects for processing
    sorted_dates = sorted(dates, key=lambda x: datetime.strptime(x["start"], "%Y-%m-%d"))
    merged = [sorted_dates[0]]

    for current in sorted_dates[1:]:
        last = merged[-1]
        last_end = datetime.strptime(last["end"], "%Y-%m-%d")
        current_start = datetime.strptime(current["start"], "%Y-%m-%d")

        # Check if the current range is consecutive or overlapping
        if current_start <= last_end + timedelta(days=1):
            last["end"] = max(last["end"], current["end"], key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
        else:
            merged.append(current)

    return merged


def generate_human_output(
    info_by_park_id, start_date, end_date, gen_campsite_info=False
):
    out = []
    has_availabilities = False
    for park_id, info in info_by_park_id.items():
        current, maximum, available_dates_by_site_id, park_name = info
        if current:
            emoji = Emoji.SUCCESS.value
            has_availabilities = True
        else:
            emoji = Emoji.FAILURE.value

        out.append(
            "{emoji} {park_name} ({park_id}): {current} site(s) available out of {maximum} site(s)".format(
                emoji=emoji,
                park_name=park_name,
                park_id=park_id,
                current=current,
                maximum=maximum,
            )
        )

        # Displays campsite ID and availability dates.
        if gen_campsite_info and available_dates_by_site_id:
            for site_id, dates in available_dates_by_site_id.items():
                out.append(
                    "  * Site {site_id} is available on the following dates:".format(
                        site_id=site_id
                    )
                )
                out.append(
                    "    https://www.recreation.gov/camping/campsites/{site_id}".format(
                        site_id=site_id
                    )
                )
                for date in dates:
                    out.append(
                        "    * {start} -> {end}".format(
                            start=date["start"], end=date["end"]
                        )
                    )

    if has_availabilities:
        out.insert(
            0,
            "there are campsites available from {start} to {end}!!!".format(
                start=start_date.strftime(DateFormat.INPUT_DATE_FORMAT.value),
                end=end_date.strftime(DateFormat.INPUT_DATE_FORMAT.value),
            ),
        )
    else:
        out.insert(0, "There are no campsites available :(")
    return "\n".join(out), has_availabilities


def generate_json_output(info_by_park_id):
    availabilities_by_park_id = {}
    has_availabilities = False
    for park_id, info in info_by_park_id.items():
        current, _, available_dates_by_site_id, park_name = info
        if current:
            has_availabilities = True
            availabilities_by_park_id[park_id] = {
                "name": park_name,
                "sites": available_dates_by_site_id,
            }

    return json.dumps(availabilities_by_park_id), has_availabilities


def remove_comments(lines: list[str]) -> list[str]:
    new_lines = []
    for line in lines:
        if line.startswith("#"):  # Deal with comment as the first character
            continue

        line = line.split(" #")[0]
        stripped = line.strip()
        if stripped != "":
            new_lines.append(stripped)

    return new_lines


def send_telegram_message(chat_id, bot_token, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    response = requests.post(url, data=data)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Error sending message to Telegram: {e.response.text}")
        raise


def escape_markdown(text):
    """Escape markdown characters."""
    escape_chars = [ '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!' ]
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


def login(username, password):
    login_url = 'https://www.recreation.gov/api/accounts/login'

    headers = {
        "authority": "www.recreation.gov",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.recreation.gov",
        "referer": "https://www.recreation.gov/",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36"
    }

    payload = {
        'username': username,
        'password': password
    }

    with requests.Session() as session:
        session.headers.update(headers)
        response = session.post(login_url, json=payload)

        if response.status_code == 200:
            print("Login successful")
            return session, response.json()
        else:
            print("Login failed")
            raise Exception("Login failed")


def add_to_cart(session, access_token, park_id, campsite_id, start_date, end_date):
    headers = {
        "authority": "www.recreation.gov",
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.recreation.gov",
        "referer": "https://www.recreation.gov/camping/campgrounds/262763",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36",
        "authorization": f"Bearer {access_token}",
    }
    session.headers.update(headers)
    url = f'https://www.recreation.gov/api/camps/reservations/campgrounds/262763/multi'
    payload = {
        "reservations": [
            {
            "account_id": "cpl8p1gvae84ss9ug750",
            "campsite_id": "10178753",
            "check_in": "2025-05-04T00:00:00.000Z",
            "check_out": "2025-05-05T00:00:00.000Z",
            }
        ],
        }
    print(url)
    response = session.post(url, json=payload)
    if response.status_code == 200:
        print("Campsite added to cart successfully")
        print(response.json())
    else:
        print("Failed to add campsite to cart")
        print(f"Error: {response.json()}")


def main(parks, json_output=False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    CAMPSITES_JSON = os.path.join(SCRIPT_DIR, "campsites.json")
    print(f"Campsite JSON file: {CAMPSITES_JSON}")
    print(f"Parks: {parks}")
    print(f"Duration: {args.start_date} to {args.end_date}")

    excluded_site_ids = []

    if args.exclusion_file:
        with open(args.exclusion_file, "r") as f:
            excluded_site_ids = f.readlines()
            excluded_site_ids = [l.strip() for l in excluded_site_ids]
            excluded_site_ids = remove_comments(excluded_site_ids)

    info_by_park_id = {}
    for park_id in parks:
        info_by_park_id[park_id] = check_park(
            park_id,
            args.start_date,
            args.end_date,
            args.campsite_type,
            args.campsite_ids,
            nights=args.nights,
            weekends_only=args.weekends_only,
            excluded_site_ids=excluded_site_ids,
        )

    output, has_availabilities = generate_json_output(info_by_park_id)

    msg, has_availabilities = generate_human_output(
        info_by_park_id,
        args.start_date,
        args.end_date,
        args.show_campsite_info,
    )

    # If campsites.json exists, compare old data with new output by parsing JSON data
    if os.path.exists(CAMPSITES_JSON):
        with open(CAMPSITES_JSON, "r") as old_file:
            try:
                old_json_data = json.load(old_file)
            except json.JSONDecodeError:
                old_json_data = None
        new_json_data = json.loads(output)
        if old_json_data != new_json_data:
            print("Differences found in campsites.json:")
            print(output)
            print("-" * 50)
            print(msg)
    
            # Prettify JSON output and write it to a file named "campsites.json"
            pretty_output = json.dumps(new_json_data, indent=4)
            with open(CAMPSITES_JSON, "w") as json_file:
                json_file.write(pretty_output)
            
            # Send a notification to the user
            title = f"*Changed campsites availability*\n"
            message = title + escape_markdown(msg)
            if args.chat_id and args.bot_token:
                send_telegram_message(args.chat_id, args.bot_token, message)
        else:
            print("No differences found in campsites.json.")
    else:
        # Prettify JSON output and write it to a file named "campsites.json"
        pretty_output = json.dumps(output, indent=4)
        with open(CAMPSITES_JSON, "w") as json_file:
            json_file.write(pretty_output)
    
    if has_availabilities:
        # Ensure required arguments are provided
        if not args.username or not args.password or not args.selenium_host:
            print("Username, password, and Selenium host are required for adding to cart.")
            return has_availabilities
        

        #
        # Create Selenium WebDriver instance
        #

        # Get the Selenium host and port from command line arguments
        selenium_host = args.selenium_host
        selenium_port = args.selenium_port if args.selenium_port else 4444
        
        # Correctly construct the Selenium WebDriver URL
        selenium_url = f"http://{selenium_host}:{selenium_port}/wd/hub"
        print(f"Selenium URL: {selenium_url}")

        # Validate the Selenium server connection
        try:
            response = requests.get(f"http://{selenium_host}:{selenium_port}/status")
            if response.status_code != 200:
                print("Selenium server is not running or not reachable.")
                return has_availabilities
        except requests.exceptions.RequestException as e:
            print(f"Error connecting to Selenium server: {e}")
            return has_availabilities

        # Create the Selenium WebDriver instance
        chrome_options = webdriver.ChromeOptions()
        # chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--start-fullscreen')
        try:
            driver = webdriver.Remote(
                command_executor=selenium_url,
                options=chrome_options
            )
        except Exception as e:
            print(f"Error initializing Selenium WebDriver: {e}")
            return has_availabilities

        
        #
        # Perform the necessary Selenium operations here
        #
        try:
            #
            # Login to recreation.gov
            #

            # Open the login page
            driver.get("https://www.recreation.gov/log-in")
            
            # Wait for the page to load the field name 'email'
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "email"))
            )
            print("Page loaded.")
            
            # Find the username and password fields and enter the credentials
            username_field = driver.find_element(By.XPATH, "//input[@id='email']")
            password_field = driver.find_element(By.XPATH, "//input[@id='rec-acct-sign-in-password']")
            username_field.send_keys(args.username)
            password_field.send_keys(args.password)
            print("Credentials entered.")

            # Find the login button and click it
            # login_submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_submit_button = driver.find_element(By.CLASS_NAME, "rec-acct-sign-in-btn")

            # Set focus on button
            driver.execute_script("arguments[0].focus();", login_submit_button)
            driver.execute_script("arguments[0].click();", login_submit_button)
            print("Login button clicked.")
            
            # Wait for class 'nav-profile-dropdown'
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "nav-profile-dropdown"))
                )
            except TimeoutException:
                print("Login failed or took too long.")
                return has_availabilities
            print("Login successful.")


            #
            # Add to cart
            #
            for park_id in parks:
                for site_id, dates in info_by_park_id[park_id][2].items():
                    for date in merge_consecutive_dates(dates):
                        
                        # Format the start and end dates
                        start_date = date["start"]
                        end_date = date["end"]
                        print(f"Adding site {site_id} to cart from {start_date} to {end_date}")

                        # Open the campsite page
                        campsite_url = f"https://www.recreation.gov/camping/campsites/{site_id}"
                        driver.get(campsite_url)
                        print(f"Opened campsite page: {campsite_url}")

                        # Wait for the button with class 'next-prev-button'
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CLASS_NAME, "next-prev-button"))
                            )
                        except TimeoutException:
                            print("Failed to load the campsite page or took too long.")
                            continue
                        print("Campsite page loaded.")
                        
                        # Format dates: date should look like April 3, 2025
                        start_date_formatted = datetime.strptime(start_date, "%Y-%m-%d").strftime("%B %d, %Y")
                        end_date_formatted = datetime.strptime(end_date, "%Y-%m-%d").strftime("%B %d, %Y")

                        for idx in range(5):
                            # Find all headers with class 'heading h5-normal'
                            headers = driver.find_elements(By.XPATH, "//h2[@class='heading h5-normal']")
                            print([header.text for header in headers])

                            # Get the first day of next month from last header
                            # Header looks like this: "April 2025"
                            next_month = datetime.strptime(headers[-1].text, "%B %Y") + timedelta(days=31)
                            next_month_formatted = next_month.strftime("%B %Y")
                            print(f"Next month: {next_month_formatted}")

                            # Headers look like this: "April 2025"
                            # Check start date and end date is in the month of header
                            is_found = False
                            start_date_month = datetime.strptime(start_date, "%Y-%m-%d").strftime("%B %Y")
                            end_date_month = datetime.strptime(end_date, "%Y-%m-%d").strftime("%B %Y")

                            if not (any(start_date_month in header.text for header in headers) and any(end_date_month in header.text for header in headers)):
                                print("Start date and end date not found in the month header.")
                                # Find next button with class 'next-prev-button' and aria-label 'Next'
                                next_button = driver.find_element(By.XPATH, "//button[@aria-label='Next']")
                                driver.execute_script("arguments[0].focus();", next_button)
                                driver.execute_script("arguments[0].click();", next_button)

                                # Wait for the next button with class 'next-prev-button' and aria-label 'Next'
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.XPATH, "//button[@aria-label='Next']"))
                                )
                                
                                continue
                            else:
                                print("Start date and end date found in the month header.")
                                
                                # Find the button with the text "Clear Dates"
                                # It cannot be existed in the page
                                try:
                                    clear_dates_button = driver.find_element(By.XPATH, "//button[.//span[text()='Clear Dates']]")
                                    driver.execute_script("arguments[0].focus();", clear_dates_button)
                                    driver.execute_script("arguments[0].click();", clear_dates_button)
                                    print("Clear Dates button clicked.")
                                except Exception as e:
                                    print(f"Clear Dates button not found or error occurred: {e}")

                                break
                        
                        # Find the div tag where aria-label contains start_date_formatted
                        start_date_div = driver.find_element(By.XPATH, f"//div[contains(@aria-label, '{start_date_formatted}')]")
                        end_date_div = driver.find_element(By.XPATH, f"//div[contains(@aria-label, '{end_date_formatted}')]")

                        print(f"Start date div: {start_date_div.get_attribute('aria-label')}")
                        print(f"End date div: {end_date_div.get_attribute('aria-label')}")

                        # Click the start date div
                        driver.execute_script("arguments[0].focus();", start_date_div)
                        driver.execute_script("arguments[0].click();", start_date_div)
                        print("Start date div clicked.")

                        # Click the end date div
                        driver.execute_script("arguments[0].focus();", end_date_div)
                        driver.execute_script("arguments[0].click();", end_date_div)
                        print("End date div clicked.")

                        # Wait for the button with id 'add-cart-campsite'
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.ID, "add-cart-campsite"))
                            )
                        except TimeoutException:
                            print("Failed to load the add to cart button or took too long.")
                            continue
                        print("Add to cart button loaded.")

                        # Find the button with id 'add-cart-campsite'
                        add_to_cart_button = driver.find_element(By.ID, "add-cart-campsite")
                        driver.execute_script("arguments[0].focus();", add_to_cart_button)
                        driver.execute_script("arguments[0].click();", add_to_cart_button)
                        print("Add to cart button clicked.")

                        # Wait for the button with class 'change-campsite-date-btn'
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CLASS_NAME, "change-campsite-date-btn"))
                        )
                        print("Change campsite date button loaded.")
        except Exception as e:
            print(f"Error during WebDriver operation: {e}")
        finally:
            # Save current page to file
            # with open("page_source.html", "w") as f:
            #     f.write(driver.page_source)

            # Close the Selenium WebDriver
            driver.quit()

        return has_availabilities


if __name__ == "__main__":
    parser = CampingArgumentParser()
    args = parser.parse_args()

    print(datetime.now(), "-" * 80)
    print(args)

    if args.debug:
        LOG.setLevel(logging.DEBUG)

    main(args.parks, json_output=args.json_output)
