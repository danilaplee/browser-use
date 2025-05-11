# This is a fork of https://github.com/browser-use/browser-use/ 
built here https://github.com/danilaplee/browser-use

## Docker Compose Sample

```
networks:
  db-tier:
    driver: bridge
services:
  db:
    image: postgres
    shm_size: 128mb
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: browser-use
      POSTGRES_USER: postgres
    networks:
      - db-tier
    ports:
      - "127.0.0.1:5432:5432"
  browser:
    depends_on:
      - db
    image: browseruser/browser-user
    environment:
      # - OLLAMA_HOST=http://host.docker.internal:11434
      - OLLAMA_HOST=${OLLAMA_HOST}
      - ERROR_WEBHOOK_URL=http://localhost:3000
      - NOTIFY_WEBHOOK_URL=http://localhost:3000
      - METRICS_WEBHOOK_URL=http://localhost:3000
      - STATUS_WEBHOOK_URL=http://localhost:3000
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/browser-use
      - PYTHONUNBUFFERED=1
      - BROWSER_USE_LOGGING_LEVEL=info
      - ANONYMIZED_TELEMETRY=false
      - DISPLAY=:99
      - RESOLUTION=1920x1080x24
      - VNC_PASSWORD=vncpassword
      - CHROME_PERSISTENT_SESSION=true
      - RESOLUTION_WIDTH=1920
      - RESOLUTION_HEIGHT=1080
      - APP_PORT=9000
    ports:
      - "9000:8000"
    volumes:
      - ./videos:/app/videos/
    # post_start:
      # - command:  /usr/bin/xvfb-run --listen-tcp --server-args="-screen 0 ${GEOMETRY} -fbdir /var/tmp -listen tcp -noreset -ac +extension RANDR" /usr/bin/fluxbox -display ${DISPLAY}
        # user: root
        # privileged: true
        # environment:
          # - GEOMETRY="1280""x""720""
          # - FOO=BAR
    networks:
      - db-tier
      - default
  server:
    depends_on:
      - browser
    image: joseluisq/static-web-server
    volumes:
      - ./videos:/public/app/videos/
    networks:
      - default
    ports:
      - "9060:80"
```

### This will run a server on port 9000 that will accept the following requests:

```
curl -X POST http://localhost:9000/run -H "Content-Type: application/json" -d '{  
    "task": "get title of google homepage",
    "llm_config": {
      "provider": "deepseek",
      "model_name": "deepseek-chat"
    },
    "browser_config": {
      "headless": true,
      "disable_security": true
    },
    "max_steps": 5,
    "use_vision": false,
    "memory_interval":5,
    "planner_interval":2
  }'

```
### And gives the following response:
```
{
   "task":"get title of google homepage",
   "result":"The title of the Google homepage is 'Google'.",
   "success":true,
   "steps_executed":2,
   "error":null,
   "videopath":"/app/videos/716165c64cc810e7468d6560f06754f2.webm"
}
```
### The video is served on the on the address https://localhost:9060/app/videos/716165c64cc810e7468d6560f06754f2.webm

## Queue System

### To submit a task you need to make a request to the queues api:
```
curl -X POST http://localhost:9000/api/v1/run -H "Content-Type: application/json" -d '{  
    "task": "get title of google homepage",
    "llm_config": {
      "provider": "deepseek",
      "model_name": "deepseek-chat"
    },
    "browser_config": {
      "headless": true,
      "disable_security": true
    },
    "max_steps": 20,
    "use_vision": false,
    "memory_interval":5,
    "planner_interval":2
  }'
```
### The response would be in this case something like this:
```
{"task_id":17}  
```

### You can get the status of the task by polling the status api:
```
 curl http://localhost:9000/api/v1/task/17/status
```
### The response would be the status of the job:
```
{
   "task_id":17,
   "status":"completed",
   "result":"{\"videopath\": \"/app/videos/1e85b0c4c88fa5084e0642151c5e6020.webm\", \"result\": \"The title of the Google homepage is 'Google'.\", \"task\": \"get title of google homepage\", \"steps_executed\": 2, \"success\": true}",
   "error":null
}
```
         