#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers
export BROWSER_USE_DEBUG=true  # Ativar modo de debug para mais logs

echo "Iniciando script de inicialização com timeout de segurança..."

# Função para executar comando com timeout
run_with_timeout() {
    local timeout=$1
    local cmd=$2
    local msg=$3
    
    echo "Executando: $msg"
    
    # Executar comando em background
    eval "$cmd" &
    local pid=$!
    
    # Aguardar pelo término do comando com timeout
    local counter=0
    while kill -0 $pid 2>/dev/null; do
        if [ $counter -ge $timeout ]; then
            echo "TIMEOUT após $timeout segundos. Encerrando processo $pid..."
            kill -9 $pid 2>/dev/null
            return 1
        fi
        sleep 1
        counter=$((counter + 1))
    done
    
    wait $pid
    return $?
}

# Garantir que temos acesso ao Xvfb
if [ ! -f /usr/bin/Xvfb ]; then
    echo "Xvfb não está instalado. Tentando instalar..."
    apt-get update && apt-get install -y xvfb
    if [ $? -ne 0 ]; then
        echo "Não foi possível instalar o Xvfb. Usando modo headless puro."
        export BROWSER_USE_HEADLESS=true
    fi
fi

# Verificar se os navegadores Playwright já estão instalados
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium-" ]; then
    echo "Navegadores Playwright não encontrados. Tentando instalar com timeout de 120 segundos..."
    run_with_timeout 120 "python3 -m playwright install chromium" "Instalando chromium"
    
    if [ $? -ne 0 ]; then
        echo "Timeout ou erro na instalação do Playwright. Continuando mesmo assim..."
        # Definir modo headless para tentar funcionar mesmo sem ter instalado corretamente
        export BROWSER_USE_HEADLESS=true
    else
        echo "Instalação do Playwright concluída com sucesso!"
    fi
else
    echo "Navegadores Playwright já instalados em $PLAYWRIGHT_BROWSERS_PATH"
fi

# Verificar se xvfb-run está disponível e funcionando
if command -v xvfb-run &> /dev/null; then
    echo "Iniciando servidor com xvfb-run..."
    
    # Testar se xvfb-run está funcionando corretamente
    xvfb-run --server-args="-screen 0 1280x1024x24" echo "Testando xvfb-run" &> /dev/null
    
    if [ $? -eq 0 ]; then
        echo "xvfb-run está funcionando corretamente."
        # Iniciar o servidor usando xvfb-run com timeout de segurança
        export DISPLAY=:99
        exec xvfb-run --server-args="-screen 0 1280x1024x24" python3 server.py
    else
        echo "xvfb-run falhou no teste. Tentando método alternativo..."
    fi
fi

echo "Usando método alternativo para iniciar Xvfb..."
# Iniciar Xvfb manualmente
Xvfb :99 -screen 0 1280x1024x24 > /dev/null 2>&1 &
export DISPLAY=:99

# Aguardar Xvfb iniciar
sleep 2

# Verificar se Xvfb iniciou corretamente
if command -v xdpyinfo &> /dev/null && xdpyinfo -display :99 &> /dev/null; then
    echo "Servidor X virtual iniciado com sucesso. Iniciando aplicação..."
    exec python3 server.py
else
    echo "Falha ao iniciar servidor X virtual. Usando modo headless puro."
    export BROWSER_USE_HEADLESS=true
    exec python3 server.py
fi 