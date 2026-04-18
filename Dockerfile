FROM nikolaik/python-nodejs:python3.11-nodejs20

# No Chromium needed! Baileys uses pure WebSocket connections.
# This saves ~300MB RAM and 2+ minutes of build time.

WORKDIR /app

# Copy all project files into the container
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies (Baileys + Express + QRCode)
RUN npm install --production

# Expose the Flask Port
EXPOSE 5000

# Start script
CMD ["sh", "start.sh"]
