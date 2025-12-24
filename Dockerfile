# Step 1: Use a Python image (Slim version keeps it fast and small)
FROM python:3.9-slim

# Step 2: Install FFmpeg (The actual software, not just the library)
# We combine these to keep the Docker image size smaller
RUN apt-get update && \
    apt-get install -y ffmpeg --no-install-recommends && \
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

# Step 7: Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
