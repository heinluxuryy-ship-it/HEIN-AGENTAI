# Uses official Python+Node combo image — NO Chromium needed (Baileys = pure WebSocket)
FROM nikolaik/python-nodejs:python3.11-nodejs20

WORKDIR /app

# Copy all project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies (Baileys + Express + QRCode)
RUN npm install --production

# Railway injects the PORT env var automatically.
# Flask will bind to it. The bridge always uses 5001 internally.
EXPOSE 5000

# Make start script executable
RUN chmod +x start.sh

# Launch both Node bridge + Python Flask
CMD ["sh", "start.sh"]
