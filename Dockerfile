# Start with an official Python image
FROM python:3.9

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV VIRTUAL_ENV=/app/venv
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    ca-certificates \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and npm (LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm

# Install Hardhat globally
RUN npm install -g hardhat

# Install Foundry (includes forge, cast, anvil)
RUN curl -L https://foundry.paradigm.xyz | bash \
    && /root/.foundry/bin/foundryup

# Add Foundry to PATH
ENV PATH="/root/.foundry/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy project files (if needed)
COPY . /app

# Create virtual environment
RUN python -m venv $VIRTUAL_ENV

# Set PATH to use virtualenv packages
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade pip

# Install Python dependencies
RUN pip install -r requirements.txt

# Install Node.js dependencies (if using a frontend or API)
#RUN cd frontend && npm install || true

# Copy supervisord config (to manage multiple processes)
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the required port (Google App Engine listens on 8080)
EXPOSE 8080

# Start services using supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
