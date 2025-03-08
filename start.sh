#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers

# Instalar navegadores Playwright se não estiverem instalados
echo "Verificando instalação dos navegadores Playwright..."
python -m playwright install chromium

# Verificar se xvfb-run está disponível
if command -v xvfb-run &> /dev/null; then
    echo "Iniciando servidor com xvfb-run..."
    # Iniciar o servidor usando xvfb-run
    exec xvfb-run --server-args="-screen 0 1280x1024x24" python server.py
else
    # Configurar para usar chromium em modo headless puro
    echo "xvfb-run não disponível, iniciando em modo headless puro"
    export BROWSER_USE_HEADLESS=true
    exec python server.py
fi 