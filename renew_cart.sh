#!/bin/sh
exec > /proc/1/fd/1 2>/proc/1/fd/2
/usr/local/bin/python3 /app/renew_cart.py --bot-token=${BOT_TOKEN} --chat-id=${CHAT_ID} --selenium-host ${SELENIUM_HOST} --selenium-port ${SELENIUM_PORT} --username ${USERNAME} --password ${PASSWORD} --debug