#!/bin/sh

/usr/local/bin/python3 /app/run.py --start-date ${START_DATE} --end-date ${END_DATE} --parks ${PARKS} --nights=${NIGHTS} --show-campsite-info --bot-token=${BOT_TOKEN} --chat-id=${CHAT_ID} --selenium-host ${SELENIUM_HOST} --username ${USERNAME} --password ${PASSWORD}
