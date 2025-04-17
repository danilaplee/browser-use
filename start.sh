#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/tmp/playwright-browsers}
export BROWSER_USE_DEBUG=${BROWSER_USE_DEBUG:-true}
export DISPLAY=:99

echo "Iniciando script de inicialização..."

# Carregar variáveis de ambiente do arquivo .env se existir
if [ -f .env ]; then
    echo "Carregando variáveis de ambiente do arquivo .env..."
    # Usar source para carregar as variáveis corretamente
    set -a
    source .env
    set +a
else
    echo "Arquivo .env não encontrado. Usando variáveis de ambiente padrão."
    # Definir variáveis padrão para PostgreSQL
    export POSTGRES_USER=${POSTGRES_USER:-postgres}
    export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres}
    export POSTGRES_DB=${POSTGRES_DB:-browser_use}
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
    export POSTGRES_PORT=${POSTGRES_PORT:-5432}
    export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

# Verifica se o Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "Python não está instalado. Instalando..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip
fi

# Verifica se o pip está instalado
if ! command -v pip3 &> /dev/null; then
    echo "pip não está instalado. Instalando..."
    sudo apt-get install -y python3-pip
fi

# Verifica se o psutil está instalado
if ! python3 -c "import psutil" &> /dev/null; then
    echo "psutil não está instalado. Instalando..."
    pip3 install psutil
fi

# Verifica se o playwright está instalado
if ! command -v playwright &> /dev/null; then
    echo "playwright não está instalado. Instalando..."
    pip3 install playwright
    playwright install
fi

# Verifica se o PostgreSQL está instalado
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL não está instalado. Instalando..."
    sudo apt-get update
    sudo apt-get install -y postgresql postgresql-contrib
fi

# Inicia o PostgreSQL
sudo service postgresql start

# Espera o PostgreSQL iniciar
sleep 5

# Cria o banco de dados e usuário se não existirem
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'postgres' CREATEDB;" || true
sudo -u postgres psql -c "CREATE DATABASE browser_use OWNER postgres;" || true

# Verifica se as variáveis de ambiente do PostgreSQL estão configuradas
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_PASSWORD" ] || [ -z "$POSTGRES_DB" ]; then
    echo "Erro: Variáveis de ambiente do PostgreSQL não configuradas"
    echo "Por favor, configure as seguintes variáveis no arquivo .env:"
    echo "POSTGRES_USER=postgres"
    echo "POSTGRES_PASSWORD=postgres"
    echo "POSTGRES_DB=browser_use"
    exit 1
fi

# Verificar dependências
check_dependency() {
    local cmd=$1
    local pkg=$2
    if ! command -v $cmd &> /dev/null; then
        echo "$cmd não encontrado. Instalando $pkg..."
        sudo apt-get update && sudo apt-get install -y $pkg
    fi
}

# Verificar dependências básicas
check_dependency python3 python3
check_dependency pip3 python3-pip
check_dependency psql postgresql-client

# Verificar variáveis de ambiente críticas
check_env_var() {
    local var=$1
    local desc=$2
    if [ -z "${!var}" ]; then
        echo "ERRO: $desc ($var) não está definida"
        exit 1
    fi
}

# Verificar variáveis críticas
check_env_var POSTGRES_USER "Usuário do PostgreSQL"
check_env_var POSTGRES_PASSWORD "Senha do PostgreSQL"
check_env_var POSTGRES_DB "Nome do banco de dados PostgreSQL"
check_env_var POSTGRES_HOST "Host do PostgreSQL"
check_env_var POSTGRES_PORT "Porta do PostgreSQL"

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
    sudo apt-get update && sudo apt-get install -y x11-utils || {
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

# Criar diretório de logs se não existir
mkdir -p /var/log/browser-use
chmod 777 /var/log/browser-use

# Executar migrações do banco de dados
echo "Executando migrações do banco de dados..."
alembic upgrade head

# Iniciar o servidor
echo "Iniciando servidor..."
exec uvicorn main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} 