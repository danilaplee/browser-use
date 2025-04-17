FROM python:3.11-slim

# Configurar variáveis de ambiente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:$PATH"
ENV BROWSER_USE_DEBUG=true
ENV PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers
# NOTA: GOOGLE_API_KEY deve ser definida nas configurações do ambiente de deploy
# ENV GOOGLE_API_KEY=""
ENV DISPLAY=:99

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
    && rm -rf /var/lib/apt/lists/*

# Criar script xvfb-run se não estiver disponível
RUN if [ ! -f /usr/bin/xvfb-run ]; then \
    echo '#!/bin/bash\nXvfb :99 -screen 0 1024x768x24 &\nDISPLAY=:99 "$@"' > /usr/local/bin/xvfb-run && \
    chmod +x /usr/local/bin/xvfb-run; \
    fi

# Instalar o Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Configurar diretório de trabalho
WORKDIR /app

# Copiar arquivos necessários
COPY . .

# Tornar o script de inicialização executável
RUN chmod +x start.sh

# Instalar pip atualizado
RUN python -m pip install --upgrade pip setuptools wheel

# Instalar dependências Python
RUN pip install --no-cache-dir -e .

# Instalar pacotes Python adicionais necessários
RUN pip install --no-cache-dir fastapi uvicorn langchain-google-genai

# Pré-instalar Playwright durante o build com tratamento de erros
RUN python -m pip install playwright && \
    echo "Instalando navegadores Playwright..." && \
    python -m playwright install chromium || \
    echo "Aviso: Falha na instalação do Playwright durante o build. Será tentado novamente na inicialização."

# Expor porta para a API
EXPOSE 8000

# Iniciar a aplicação usando o script
CMD ["./start.sh"] 