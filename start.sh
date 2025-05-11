#!/bin/bash
if [[ -z "${IS_WORKER}" ]]
then
    uvicorn server:app --host 0.0.0.0 --port ${APP_PORT}
else 
    /usr/bin/xvfb-run python3 queues.py
fi