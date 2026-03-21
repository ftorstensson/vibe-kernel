# Use the industrial-standard slim Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire Kernel structure
COPY core/ core/
COPY pods/ pods/
COPY registry/ registry/
COPY schema/ schema/
COPY utils/ utils/
COPY Brain/ Brain/
COPY main.py .

# Expose port for Cloud Run
EXPOSE 8080

# Command to start the engine
CMD ["python", "main.py"]
