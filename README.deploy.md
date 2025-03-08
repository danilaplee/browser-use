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
3. Em "Build settings", selecione **Nixpacks** como o builder
4. Certifique-se de que a versão do Nixpacks é 1.30 ou superior
5. Em "Start command" deixe em branco (o comando está definido no nixpacks.toml)

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

### Problemas com Chromium

Se houver problemas com o Chrome/Chromium:

1. Verifique os logs da aplicação para erros específicos
2. Certifique-se de que o Easypanel está utilizando o arquivo nixpacks.toml
3. Se necessário, adicione a variável de ambiente `PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers` para permitir que o Playwright baixe e instale automaticamente os navegadores

### Erros na Execução do Navegador

Se o navegador não iniciar corretamente, tente:

1. Verificar se todas as dependências do sistema estão instaladas
2. Modificar a configuração `headless` para `true` 
3. Adicionar mais memória ao serviço no Easypanel

## Usando Docker em vez de Nixpacks

Se preferir usar Docker em vez do Nixpacks:

1. No Easypanel, escolha "Custom" como tipo de projeto
2. Em "Build settings", selecione **Dockerfile** como builder
3. O sistema usará o Dockerfile fornecido no repositório 