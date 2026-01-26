FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy collector code
COPY meshtastic_collector/ ./meshtastic_collector/

# Run collector
CMD ["python", "-m", "meshtastic_collector.mqtt_collector"]
