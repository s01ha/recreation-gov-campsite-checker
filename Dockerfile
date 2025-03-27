FROM python:3
USER root
COPY requirements.txt .
RUN apt-get update && \
    apt-get -y install cron vim && \
    pip install --upgrade pip --no-cache-dir && \
    pip install -r requirements.txt --no-cache-dir
WORKDIR /app
COPY *.py /app/
COPY *.json /app/
COPY clients /app/clients
COPY enums /app/enums
COPY other /app/other
COPY utils /app/utils
COPY run.sh /app/run.sh
COPY crontab /etc/cron.d/crontab
RUN chmod +x /app/run.sh
RUN chmod 0644 /etc/cron.d/crontab
RUN /usr/bin/crontab /etc/cron.d/crontab

ADD entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
