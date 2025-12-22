FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any (none obvious from requirements, but sometimes needed)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume mount point
VOLUME ["/app/data"]

# Expose web dashboard port
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
