FROM python:3.11-slim

WORKDIR /app

# Copy shared module first
COPY shared/ /app/shared/

# Copy requirements and install
COPY download_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY download_service/ /app/

# Expose port
EXPOSE 8202

# Run the service
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8202"]
