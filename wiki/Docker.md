# Docker Setup & Update Guide

## 1. Initial Setup for Updates

To allow the GitHub Repository to automatically push updates to Docker Hub, you need to configure **Secrets** in your GitHub Repository settings.

1.  Go to your Repository on GitHub -> **Settings** -> **Secrets and variables** -> **Actions**.
2.  Click **New repository secret**.
3.  Add the following two secrets:
    *   **Name**: `DOCKER_USERNAME`
        *   **Value**: Your Docker Hub Username (e.g., `l8tenever`)
    *   **Name**: `DOCKER_PASSWORD`
        *   **Value**: Your Docker Hub Password (or better: a [Docker Hub Access Token](https://hub.docker.com/settings/security)).

Once this is done, every time you push code to the `main` branch, a new Docker image will be built and pushed to Docker Hub automatically.

## 2. Using the Docker Image

### For Users (Download Only)
Users don't need the source code. They only need the `docker-compose.yml`.

Update your `docker-compose.yml` to use the online image instead of building locally:

```yaml
version: '3.8'

services:
  l8tebot:
    # REPLACE 'yourusername' with your actual Docker Hub username
    image: yourusername/l8tebot:latest
    container_name: l8tebot
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Europe/Berlin
```

### Performing an Update
When a new version is released on GitHub (and automatically pushed to Docker Hub), you can update your bot with these commands:

```bash
# 1. Pull the latest image
docker-compose pull

# 2. Restart the container with the new code
docker-compose up -d
```

## 3. Data Safety
Your data is safe!
We use **Volumes** in `docker-compose.yml`:
`- ./data:/app/data`

This means:
*   The `data` folder inside the container is mapped to the `data` folder on your server/PC.
*   When you delete or update the container, the `./data` folder on your PC remains untouched.
*   Your `config.json` and database remain safe.
