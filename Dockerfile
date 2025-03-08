FROM python:3.11-slim

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
    xvfb-run \
    gnumake \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

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

# Instalar dependências Python
RUN pip install --no-cache-dir -e .

# Instalar pacotes Python adicionais necessários
RUN pip install --no-cache-dir fastapi uvicorn

# Configurar Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers
RUN python -m playwright install chromium

# Expor porta para a API
EXPOSE 8000

# Iniciar a aplicação usando o script
CMD ["./start.sh"] 