FROM python:3.11-slim

# Configurar variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:$PATH"
ENV DISPLAY=:99

# Criar usuário não-root
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown appuser:appuser /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
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
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-noto-cjk \
    x11-utils \
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

# Criar diretório para logs
RUN mkdir -p /var/log/browser-use && \
    chown -R appuser:appuser /var/log/browser-use && \
    chmod 777 /var/log/browser-use

# Configurar diretório de trabalho
WORKDIR /app

# Copiar arquivos necessários
COPY --chown=appuser:appuser . .

# Tornar scripts executáveis
RUN chmod +x start.sh

# Instalar pip atualizado
RUN python -m pip install --upgrade pip setuptools wheel

# Instalar dependências Python
RUN pip install --no-cache-dir -e .

# Instalar pacotes Python adicionais necessários
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    langchain-google-genai \
    psycopg2-binary \
    aiohttp \
    python-dotenv \
    alembic \
    sqlalchemy \
    pydantic \
    python-jose[cryptography] \
    passlib[bcrypt] \
    python-multipart

# Pré-instalar Playwright durante o build
RUN python -m pip install playwright && \
    python -m playwright install chromium && \
    python -m playwright install-deps

# Expor porta para a API
EXPOSE 8000

# Definir variáveis de ambiente padrão
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBUG=false
ENV PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers
ENV BROWSER_USE_DEBUG=true
ENV BROWSER_USE_HEADLESS=true

# Mudar para usuário não-root
USER appuser

# Iniciar a aplicação usando o script
CMD ["./start.sh"] 