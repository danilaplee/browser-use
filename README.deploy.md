# Instruções de Deploy - Browser-use API

Este documento contém instruções para fazer deploy da API Browser-use em uma VPS usando Easypanel e Nixpacks 1.30.

## Pré-requisitos

- Uma VPS com Easypanel instalado
- Conhecimento básico de Git e Docker
- Chaves de API para os modelos de linguagem que deseja utilizar

## Preparação do Ambiente

1. Clone este repositório em sua máquina local ou diretamente na VPS
2. Copie o arquivo `.env.example` para `.env` e preencha as variáveis de ambiente necessárias

## Deploy utilizando Easypanel

### 1. Acesse o Dashboard do Easypanel

Acesse o painel do Easypanel instalado em sua VPS através do navegador.

### 2. Crie um novo projeto

1. Clique em "Create project"
2. Escolha a opção "Website" ou "Custom"
3. Preencha o nome do projeto (exemplo: "browser-use-api")
4. Configure o domínio ou subdomínio para acessar a API

### 3. Configuração do Projeto

Na tela de configuração do projeto:

1. Escolha **Build from source**
2. Insira o URL do seu repositório Git (GitHub, GitLab, etc.)
3. Em "Build settings", selecione **Dockerfile** como o builder (recomendado)
   - Alternativamente, você pode usar **Nixpacks** com a versão 1.30 ou superior
4. Em "Start command" deixe em branco (o comando está definido no Dockerfile/nixpacks.toml)

### 4. Configuração de Recursos

Configure os recursos de acordo com as necessidades da aplicação:

- CPU: Recomendado pelo menos 1 vCPU
- RAM: Mínimo de 2GB para funcionamento adequado
- Armazenamento: 10GB ou mais

### 5. Variáveis de Ambiente

Configure as variáveis de ambiente necessárias:

1. Vá para a seção "Environment Variables"
2. Adicione todas as variáveis do seu arquivo `.env` 
3. Certifique-se de adicionar pelo menos:
   - `OPENAI_API_KEY` ou outra API key necessária para o modelo de linguagem
   - `PORT` (definido como 8000)

### 6. Deploy do Projeto

1. Clique em "Deploy" para iniciar o processo de build e deploy
2. Acompanhe os logs para verificar se a build está sendo executada corretamente
3. Após a conclusão, a API estará disponível no domínio configurado

## Testando a API

Após o deploy, teste a API fazendo uma requisição HTTP para o endpoint `/health`:

```bash
curl https://seu-dominio.com/health
```

Se o retorno for `{"status": "healthy"}`, a API está funcionando corretamente.

Para testar a funcionalidade completa, faça uma requisição para o endpoint `/run`:

```bash
curl -X POST https://seu-dominio.com/run \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Busque o título da página inicial do Google",
    "model_config": {
      "provider": "openai",
      "model_name": "gpt-4o",
      "temperature": 0.0
    },
    "browser_config": {
      "headless": true,
      "disable_security": true
    },
    "max_steps": 5,
    "use_vision": true
  }'
```

## Solução de Problemas

### Problemas de Travamento na Inicialização

Se o servidor ficar travado na mensagem "Verificando instalação dos navegadores Playwright..." ou "Iniciando servidor com xvfb-run..." por mais de 10 minutos:

1. **Verifique os logs completos:** Use `docker logs -f nome-do-container` para visualizar todos os logs da aplicação e identificar onde está travando.

2. **Verifique recursos do sistema:** Certifique-se de que a VPS tem memória suficiente (mínimo 2GB recomendado). A instalação do Playwright pode falhar silenciosamente se não houver memória suficiente.

3. **Ative o modo headless puro:**
   - Adicione a variável de ambiente `BROWSER_USE_HEADLESS=true` nas configurações do projeto.
   - Esta configuração fará o navegador funcionar em modo headless puro, sem depender do Xvfb.

4. **Acesse o container e verifique o estado:**
   ```bash
   docker exec -it nome-do-container bash
   ps aux  # Para ver os processos em execução
   kill -9 PID  # Para matar processos travados se necessário
   ```

5. **Reinicie o container:** No dashboard do Easypanel, reinicie o container da aplicação.

6. **Verifique se o Playwright consegue ser executado:**
   ```bash
   docker exec -it nome-do-container bash
   python3 -c "from playwright.sync_api import sync_playwright; print('OK!' if sync_playwright().__enter__() else 'Falha')"
   ```

7. **Solução de último caso:** Se nada funcionar, modifique o arquivo `start.sh` diretamente no container para pular a verificação e instalação do Playwright, forçando o modo headless puro:
   ```bash
   docker exec -it nome-do-container bash
   echo '#!/bin/bash
   export BROWSER_USE_HEADLESS=true
   exec python3 server.py' > /app/start.sh
   chmod +x /app/start.sh
   ```
   Em seguida, reinicie o container.

### Problemas com o Docker Build

Se o build do Docker estiver falhando ou demorando muito:

1. **Construa localmente:** Construa a imagem localmente e depois faça o upload para um registro como o Docker Hub.
   ```bash
   docker build -t seu-usuario/browser-use:latest .
   docker push seu-usuario/browser-use:latest
   ```

2. **Use uma imagem pré-construída:** No Easypanel, escolha "Use existing image" e especifique `seu-usuario/browser-use:latest`.

3. **Desabilite a instalação do Playwright durante o build:** Edite o Dockerfile e comente a linha que instala o Playwright, permitindo que ele seja instalado apenas durante a inicialização.

### Problemas com o Dockerfile

Se você encontrar erros como `Unable to locate package xvfb-run` ou `Unable to locate package gnumake` durante o build:

1. **Nomes de pacotes corretos**: Certifique-se de usar os nomes corretos para os pacotes Debian. Por exemplo, use `make` em vez de `gnumake` e garanta que o `xvfb` está sendo instalado.

2. **Script xvfb-run personalizado**: O Dockerfile inclui um script personalizado para criar o utilitário `xvfb-run` se ele não estiver disponível no sistema.

3. **Dependências de X11**: Certifique-se de que o pacote `x11-utils` está instalado para ter acesso a ferramentas como `xdpyinfo`.

### Problemas com o Python

Se você encontrar erros como `python: command not found` ou `ModuleNotFoundError: No module named 'X'`:

1. **Usar o Dockerfile**: Recomendamos fortemente usar o Dockerfile fornecido, que já está configurado com todas as dependências necessárias, incluindo a versão correta do Python.

2. **Dependências do Langchain**: O servidor requer várias dependências do Langchain, incluindo:
   - `langchain-google-genai` - Para integração com o Google Generative AI
   - Outras dependências que podem ser listadas no arquivo `requirements.txt` ou `pyproject.toml`

3. **Instalar dependências manualmente**: Se estiver usando um container existente, você pode instalar as dependências faltantes:
   ```bash
   pip install langchain-google-genai
   ```

4. **Verificar erros de inicialização**: Se o servidor não mostrar logs após a inicialização, verifique erros de importação executando o script manualmente:
   ```bash
   python3 server.py
   ```

### Problemas com Nixpacks e pacotes não encontrados

Se você encontrar erros como `undefined variable 'nome-do-pacote'` durante o build com Nixpacks:

1. Verifique se o nome do pacote está correto e existe no repositório Nix
2. Para problemas com o pacote `xvfb`, use apenas `xvfb-run` que já inclui a funcionalidade necessária
3. Se necessário, edite o arquivo `nixpacks.toml` e remova os pacotes que estão causando problemas
4. **Versão alternativa do nixpacks.toml**: Se continuar tendo problemas, renomeie o arquivo `nixpacks.toml.alternative` para `nixpacks.toml` e tente novamente. Esta versão usa uma abordagem mais direta para instalar os pacotes necessários.

### Problemas com Chromium

Se houver problemas com o Chrome/Chromium:

1. Verifique os logs da aplicação para erros específicos
2. Certifique-se de que o Easypanel está utilizando o arquivo nixpacks.toml ou o Dockerfile
3. Se necessário, adicione a variável de ambiente `PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers` para permitir que o Playwright baixe e instale automaticamente os navegadores

### Erros na Execução do Navegador

Se o navegador não iniciar corretamente, tente:

1. Verificar se todas as dependências do sistema estão instaladas
2. Modificar a configuração `headless` para `true` 
3. Adicionar mais memória ao serviço no Easypanel

## Usando Docker em vez de Nixpacks

Devido aos problemas comuns com Nixpacks, recomendamos **fortemente** usar o Docker para deploy:

1. No Easypanel, escolha "Custom" como tipo de projeto
2. Em "Build settings", selecione **Dockerfile** como builder
3. O sistema usará o Dockerfile fornecido no repositório, que inclui todas as dependências necessárias

O Dockerfile foi especialmente configurado para resolver os problemas comuns de dependências e configuração do Python. 