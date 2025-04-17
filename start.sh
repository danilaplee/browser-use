#!/bin/bash

# Carregar variáveis de ambiente
if [ -f .env ]; then
    echo "Carregando variáveis de ambiente do arquivo .env..."
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "Arquivo .env não encontrado. Usando variáveis de ambiente padrão."
fi

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/tmp/playwright-browsers}
export BROWSER_USE_DEBUG=${BROWSER_USE_DEBUG:-true}
export DISPLAY=:99

echo "Iniciando script de inicialização..."

# Verificar dependências
check_dependency() {
    local cmd=$1
    local pkg=$2
    if ! command -v $cmd &> /dev/null; then
        echo "$cmd não encontrado. Instalando $pkg..."
        apt-get update && apt-get install -y $pkg
    fi
}

# Verificar dependências básicas
check_dependency python3 python3
check_dependency pip3 python3-pip
check_dependency psql postgresql-client

# Verificar dependências Python
if ! python3 -c "import psutil" &> /dev/null; then
    echo "psutil não encontrado. Instalando..."
    pip3 install psutil==5.9.6
fi

if ! command -v playwright &> /dev/null; then
    echo "playwright não encontrado. Instalando..."
    pip3 install playwright
    playwright install chromium
    playwright install-deps
fi

# Verificar variáveis de ambiente críticas
check_env_var() {
    local var=$1
    local desc=$2
    if [ -z "${!var}" ]; then
        echo "ERRO: $desc ($var) não está definida"
        exit 1
    fi
}

check_env_var POSTGRES_USER "Usuário do PostgreSQL"
check_env_var POSTGRES_PASSWORD "Senha do PostgreSQL"
check_env_var POSTGRES_DB "Nome do banco de dados PostgreSQL"

# Verificar se GOOGLE_API_KEY está definida
if [ -z "$GOOGLE_API_KEY" ]; then
    echo "⚠️ AVISO: GOOGLE_API_KEY não está definida. Isso pode causar falhas se o servidor usar langchain_google_genai."
fi

# Função para executar comando com timeout
run_with_timeout() {
    local timeout=$1
    local cmd=$2
    local msg=$3
    
    echo "Executando: $msg"
    
    eval "$cmd" &
    local pid=$!
    
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

# Verificar modo headless
if [ "$BROWSER_USE_HEADLESS" = "true" ]; then
    echo "Modo headless ativado via variável de ambiente."
    exec python3 server.py
    exit 0
fi

# Configurar Xvfb
if ! command -v Xvfb &> /dev/null; then
    echo "Xvfb não encontrado. Tentando instalar..."
    apt-get update && apt-get install -y x11-utils || {
        echo "Falha ao instalar Xvfb. Iniciando em modo headless..."
        export BROWSER_USE_HEADLESS=true
    }
fi

# Verificar navegadores Playwright
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium-" ]; then
    echo "Navegadores Playwright não encontrados. Instalando..."
    run_with_timeout 120 "python3 -m playwright install chromium" "Instalando chromium"
    
    if [ $? -ne 0 ]; then
        echo "Timeout ou erro na instalação do Playwright. Usando modo headless."
        export BROWSER_USE_HEADLESS=true
    fi
fi

# Executar migrações do banco de dados
echo "Executando migrações do banco de dados..."
alembic upgrade head

# Iniciar o servidor
echo "Iniciando servidor..."
exec uvicorn main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} 