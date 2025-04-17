FROM python:3.11-slim

# Configurar variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:$PATH"
ENV DISPLAY=:99
ENV DEBIAN_FRONTEND=noninteractive

# Criar usuário não-root
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown appuser:appuser /app

# Configurar apt para ser mais robusto
RUN echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80retries && \
    echo 'Acquire::http::Timeout "120";' >> /etc/apt/apt.conf.d/80retries && \
    echo 'Acquire::ftp::Timeout "120";' >> /etc/apt/apt.conf.d/80retries

# Limpar cache e instalar dependências básicas
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências do sistema em etapas
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    xvfb \
    libgconf-2-4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libnspr4 \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

# Instalar apenas fontes essenciais
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    fonts-liberation \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências de desenvolvimento
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    make \
    gcc \
    git \
    procps \
    dbus \
    curl \
    python3-dev \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências adicionais do Playwright
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# Criar diretório para logs
RUN mkdir -p /var/log/browser-use && \
    chown appuser:appuser /var/log/browser-use

# Configurar diretório de trabalho
WORKDIR /app

# Instalar dependências Python
RUN pip install --no-cache-dir \
    fastapi==0.104.0 \
    uvicorn==0.24.0 \
    playwright==1.40.0 \
    sqlalchemy==2.0.23 \
    asyncpg==0.29.0 \
    psycopg2-binary==2.9.9 \
    python-dotenv==1.0.0 \
    pydantic==2.5.2 \
    pydantic-settings==2.1.0 \
    python-jose[cryptography]==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    python-multipart==0.0.6 \
    aiohttp==3.9.1 \
    httpx==0.25.2 \
    psutil==5.9.6 \
    alembic==1.12.1 \
    greenlet==3.0.1 \
    posthog==3.0.0

# Instalar pacotes LangChain necessários
RUN pip install --no-cache-dir langchain==0.1.0
RUN pip install --no-cache-dir langchain-openai==0.0.5

# Instalar browsers do Playwright
RUN playwright install chromium
RUN playwright install-deps

# Copiar o código da aplicação
COPY . .

# Configurar permissões
RUN chown -R appuser:appuser /app

# Mudar para usuário não-root
USER appuser

# Expor porta
EXPOSE 8000

# Comando para iniciar a aplicação
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"] 