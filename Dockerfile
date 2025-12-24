# Use an official lightweight Python image
FROM python:3.9-slim

# Install system dependencies (FFmpeg is the key here!)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Render will use
EXPOSE 5000

# Command to run the app using Gunicorn (Production server)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
