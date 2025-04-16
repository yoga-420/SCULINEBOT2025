FROM python:3.12.10-slim

# Update packages and install curl for health check
RUN apt-get update && apt-get upgrade -y && apt-get install -y curl=7.74.0-1.3+deb11u3 && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd --create-home appuser

WORKDIR /code

# Copy files with proper ownership
COPY --chown=appuser:appuser ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY --chown=appuser:appuser . .

# Add HEALTHCHECK instruction
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:7860/ || exit 1

# Switch to non-root user
USER appuser

CMD ["gunicorn", "-b", "0.0.0.0:7860", "gpt4:app"]
