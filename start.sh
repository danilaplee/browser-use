#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers

# Instalar navegadores Playwright se não estiverem instalados
echo "Verificando instalação dos navegadores Playwright..."
python -m playwright install chromium

# Verificar se Xvfb está instalado
if command -v Xvfb &> /dev/null; then
    echo "Iniciando Xvfb..."
    Xvfb :99 -screen 0 1280x1024x24 > /dev/null 2>&1 &
    export DISPLAY=:99
    
    # Aguardar Xvfb iniciar
    sleep 2
fi

# Configurar para usar chromium em modo headless
export BROWSER_USE_HEADLESS=true

# Iniciar o servidor com Xvfb se disponível
if [ -n "$DISPLAY" ]; then
    echo "Iniciando servidor com display virtual: $DISPLAY"
    exec python server.py
else
    echo "Iniciando servidor em modo headless puro"
    exec python server.py
fi 