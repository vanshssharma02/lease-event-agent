# Multi-stage Dockerfile for lease-event-agent
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_MODE=mock

WORKDIR /app

# Install system dependencies needed for PDF processing and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY app/ app/
COPY ui/ ui/
COPY eval/ eval/
COPY scripts/ scripts/
COPY README.md CHECKLIST.md .

# Create persistent data and vector store directories
RUN mkdir -p data chroma_db

# Default port exposure: FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501

# Default launch command: runs health check / seed on start
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
