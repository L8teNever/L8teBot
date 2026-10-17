FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any (none obvious from requirements, but sometimes needed)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Tailwind (Play-Build) beim Build lokal ablegen, damit die Seite kein CDN braucht
RUN python -c "import urllib.request as u; open('web/static/js/tailwind.js','wb').write(u.urlopen('https://cdn.tailwindcss.com?plugins=forms,container-queries').read())"

# Create volume mount point
VOLUME ["/app/data"]

# Expose web dashboard port
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
