# Carefold Docker Environment

This directory contains the canonical Docker Compose configuration for running the Carefold stack locally.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.
- A `.env` file in this directory.

## Vault Key Setup (Required)

Carefold encrypts chat history locally. You must generate a Vault Key (KEK) before starting the services.

1. Copy the example environment file:2

   ```bash
   cp deploy/docker/.env.example deploy/docker/.env
   ```

2. Generate a secure key and add it to your `.env` file:

    ```bash

    echo "CAREFOLD_VAULT_KEK=$(openssl rand -hex 32)" >> deploy/docker/.env
    ```
    > Warning: Keep this key safe. If you lose it, previously saved encrypted chats cannot be recovered.

## Starting the Stack

To start the backend and frontend from the repository root:

    ```bash
    docker compose up -d
    ```

To start the stack with local AI (Ollama), use the `local-ai` profile:

    ```bash
    docker compose --profile local-ai up -d
    ```

## Pulling AI Models (Ollama)

If you started the stack with the local-ai profile, you can pull a lightweight model into the Ollama container:

    ```bash
    docker compose exec ollama ollama run llama3.2
    ```

## Verifying Healthchecks

To confirm all services are running and healthy:

    ```bash
    docker compose ps
    ```
The `STATUS` column should show `(healthy)` for the backend and web services.

## Stopping the Stack

To stop and remove the containers:

    ```bash
    docker compose down
    ```