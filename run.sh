#!/bin/sh
exec > /proc/1/fd/1 2>/proc/1/fd/2
/usr/local/bin/python3 /app/run.py --start-date ${START_DATE} --end-date ${END_DATE} --parks ${PARKS} --nights=${NIGHTS} --show-campsite-info --campsite-type-excluded ${CAMPSITE_TYPE_EXCLUDED} --bot-token=${BOT_TOKEN} --chat-id=${CHAT_ID} --selenium-host ${SELENIUM_HOST} --username ${USERNAME} --password ${PASSWORD} --loop --loop-interval ${LOOP_INTERVAL}
