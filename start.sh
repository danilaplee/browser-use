#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers
export BROWSER_USE_DEBUG=true  # Ativar modo de debug para mais logs
export DISPLAY=:99

echo "Iniciando script de inicialização com timeout de segurança..."

# Verificar se GOOGLE_API_KEY está definida
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "⚠️ AVISO: GOOGLE_API_KEY não está definida. Isso pode causar falhas se o servidor usar langchain_google_genai."
    echo "Para solucionar, defina a variável GOOGLE_API_KEY nas configurações do ambiente."
fi

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

# Verificar se devemos usar modo headless
if [ "$BROWSER_USE_HEADLESS" = "true" ]; then
    echo "Modo headless ativado via variável de ambiente. Ignorando Xvfb."
    echo "Iniciando servidor em modo headless puro..."
    exec python3 server.py
    exit 0
fi

# Verifica se o Xvfb está instalado
if ! command -v Xvfb &> /dev/null; then
    echo "Xvfb não encontrado. Tentando instalar..."
    apt-get update && apt-get install -y x11-utils || {
        echo "Falha ao instalar Xvfb. Iniciando em modo headless..."
        export BROWSER_USE_HEADLESS=true
    }
fi

# Verifica se o xvfb-run está disponível
if ! command -v xvfb-run &> /dev/null; then
    echo "xvfb-run não encontrado. Criando script alternativo..."
    echo '#!/bin/bash
Xvfb :99 -screen 0 1024x768x24 &
DISPLAY=:99 "$@"
' > /usr/local/bin/xvfb-run
    chmod +x /usr/local/bin/xvfb-run
fi

# Verificar se os navegadores Playwright já estão instalados
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium-" ]; then
    echo "Navegadores Playwright não encontrados. Tentando instalar com timeout de 120 segundos..."
    run_with_timeout 120 "python3 -m playwright install chromium" "Instalando chromium"
    
    if [ $? -ne 0 ]; then
        echo "Timeout ou erro na instalação do Playwright. Usando modo headless puro."
        export BROWSER_USE_HEADLESS=true
        exec python3 server.py
        exit 0
    else
        echo "Instalação do Playwright concluída com sucesso!"
    fi
else
    echo "Navegadores Playwright já instalados em $PLAYWRIGHT_BROWSERS_PATH"
fi

# Testar se o Xvfb funciona corretamente
Xvfb -help >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Erro ao executar Xvfb. Usando modo headless puro."
    export BROWSER_USE_HEADLESS=true
    exec python3 server.py
    exit 0
fi

# Verificar se xvfb-run está disponível e funcionando
if command -v xvfb-run &> /dev/null; then
    echo "Iniciando servidor com xvfb-run..."
    
    # Testar se xvfb-run está funcionando corretamente
    xvfb-run --server-args="-screen 0 1280x1024x24" echo "Testando xvfb-run" &> /dev/null
    
    if [ $? -eq 0 ]; then
        echo "xvfb-run está funcionando corretamente."
        # Iniciar o servidor usando xvfb-run com timeout de segurança
        echo "Iniciando servidor..."
        exec xvfb-run --server-args="-screen 0 1280x1024x24" python3 server.py
        exit 0
    else
        echo "xvfb-run falhou no teste. Usando modo headless puro."
        export BROWSER_USE_HEADLESS=true
        exec python3 server.py
        exit 0
    fi
fi

echo "Nenhum método de inicialização X virtual funcionou. Usando modo headless puro."
export BROWSER_USE_HEADLESS=true

# Executa migrações do banco de dados
echo "Executando migrações do banco de dados..."
alembic upgrade head

# Inicia o servidor
echo "Iniciando servidor..."
if command -v xvfb-run &> /dev/null; then
    xvfb-run python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
else
    python3 -m uvicorn api:app --host 0.0.0.0 --port 8000
fi 