# Docker Setup Guide

## Overview
This project is fully Dockerized for easy deployment and development. The Docker setup includes:

- **Python 3.11** with all required dependencies
- **Flask web server** for the CSV editor interface
- **Health checks** to ensure the application is running
- **Volume mounts** for persistent data and live editing

## Quick Start

### Using docker-compose (Recommended)

```bash
# Start the application
docker-compose up

# Start in background
docker-compose up -d

# Stop the application
docker-compose down
```

### Using the start script

```bash
chmod +x start-docker.sh
./start-docker.sh
```

## Accessing the Application

Once running, the application is available at:
```
http://localhost:5001
```

## Volume Mounts

The Docker setup includes the following volume mounts:

| Local Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./output` | `/app/output` | CSV output files and reports |
| `./source` | `/app/source` | IB activity statement input files |
| `./templates` | `/app/templates` | HTML templates (for live editing) |
| `./static` | `/app/static` | CSS and static assets (for live editing) |

## Build and Rebuild

```bash
# Build the image from scratch
docker-compose build

# Rebuild without using cache
docker-compose build --no-cache

# Rebuild and start
docker-compose up --build
```

## Checking Container Status

```bash
# View running containers
docker-compose ps

# View container logs
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# View logs for specific service
docker-compose logs vmi-editor
```

## Docker Cleanup

```bash
# Stop and remove containers
docker-compose down

# Remove unused images
docker image prune

# Remove all stopped containers
docker container prune

# Full cleanup (containers, images, volumes)
docker-compose down --volumes --remove-orphans
docker system prune -a
```

## Troubleshooting

### Application not responding
```bash
# Check container status
docker-compose ps

# View error logs
docker-compose logs vmi-editor

# The healthcheck shows (healthy) when the app is running
```

### Port already in use
If port 5001 is already in use, modify `docker-compose.yml`:
```yaml
ports:
  - "5002:5001"  # Map to a different port
```

### File permissions issues
If you encounter file permission issues with mounted volumes:
```bash
# Ensure output and source directories exist
mkdir -p output source

# Set appropriate permissions
chmod 755 output source
```

## Environment Variables

The following environment variables are configured:

- `FLASK_APP=app.py` - Flask application entry point
- `FLASK_ENV=production` - Flask environment mode
- `FLASK_PORT=5001` - Flask server port
- `PYTHONUNBUFFERED=1` - Ensure unbuffered output

## Health Check

The Docker container includes a health check that:
- Pings the Flask application every 30 seconds
- Marks the container as "healthy" when responding
- Waits 10 seconds after startup before first check

View health status:
```bash
docker-compose ps  # Look at STATUS column
```

## Development vs Production

### Current Setup (Development)
- Uses Flask development server
- Hot-reload friendly with volume mounts
- Unbuffered output for logging

### For Production
For production deployment, consider:
1. Using a production WSGI server (Gunicorn, uWSGI)
2. Adding environment-specific configurations
3. Implementing proper logging and monitoring
4. Using a reverse proxy (nginx, Traefik)

Update the Dockerfile CMD to use Gunicorn:
```dockerfile
RUN pip install gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "4", "app:app"]
```

## Docker Image Details

- **Base Image**: `python:3.11-slim`
- **Working Directory**: `/app`
- **Exposed Port**: `5001`
- **Image Name**: `investicine_saskaita_di-vmi-editor`
- **Container Name**: `vmi-csv-editor`

## Additional Commands

```bash
# Execute command in running container
docker-compose exec vmi-editor python -c "import sys; print(sys.version)"

# Access container shell
docker-compose exec vmi-editor /bin/bash

# Update dependencies without rebuilding
docker-compose exec vmi-editor pip install -r requirements.txt

# View image layers
docker image history investicine_saskaita_di-vmi-editor
```

## Files

- `Dockerfile` - Container build configuration
- `docker-compose.yml` - Multi-container orchestration
- `.dockerignore` - Files to exclude from build context
- `start-docker.sh` - Bash script for easy startup (macOS/Linux)

## References

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Flask Docker Guide](https://flask.palletsprojects.com/en/latest/deploying/docker/)

