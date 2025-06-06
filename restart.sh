#!/bin/bash
cd /container/recreation-gov-campsite-checker
/usr/bin/docker compose down
/usr/bin/docker compose up -d --build
