#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers

# Garantir que temos acesso ao Xvfb
if [ ! -f /usr/bin/Xvfb ]; then
    echo "Xvfb não está instalado. Tentando instalar..."
    apt-get update && apt-get install -y xvfb
    if [ $? -ne 0 ]; then
        echo "Não foi possível instalar o Xvfb. Usando modo headless puro."
        export BROWSER_USE_HEADLESS=true
        exec python3 server.py
        exit
    fi
fi

# Instalar navegadores Playwright se não estiverem instalados
echo "Verificando instalação dos navegadores Playwright..."
python3 -m playwright install chromium

# Verificar se xvfb-run está disponível
if command -v xvfb-run &> /dev/null; then
    echo "Iniciando servidor com xvfb-run..."
    # Iniciar o servidor usando xvfb-run
    exec xvfb-run --server-args="-screen 0 1280x1024x24" python3 server.py
else
    echo "xvfb-run não encontrado. Criando servidor X virtual manualmente..."
    # Iniciar Xvfb manualmente
    Xvfb :99 -screen 0 1280x1024x24 > /dev/null 2>&1 &
    export DISPLAY=:99
    
    # Aguardar Xvfb iniciar
    sleep 2
    
    # Verificar se Xvfb iniciou corretamente
    if xdpyinfo -display :99 &> /dev/null; then
        echo "Servidor X virtual iniciado com sucesso. Iniciando aplicação..."
        exec python3 server.py
    else
        echo "Falha ao iniciar servidor X virtual. Usando modo headless puro."
        export BROWSER_USE_HEADLESS=true
        exec python3 server.py
    fi
fi 