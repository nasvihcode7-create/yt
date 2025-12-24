# Step 1: Use Python 3.12 slim image (updated from 3.9)
FROM python:3.12-slim

# Step 2: Install FFmpeg and curl for debugging
RUN apt-get update && \
    apt-get install -y ffmpeg curl --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Step 3: Set the internal folder for the app
WORKDIR /app

# Step 4: Install Python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 5: Copy your code and the cookie file into the image
COPY . .

# Step 6: Set the environment variable for Flask
ENV PORT=5000

# Step 7: Run the application with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]
