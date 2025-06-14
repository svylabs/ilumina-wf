# Start with an official Python image
FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV VIRTUAL_ENV=/app/venv
ENV PYTHONUNBUFFERED=1
ENV GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    vim \
    git \
    unzip \
    ca-certificates \
    supervisor \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and npm (LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm

RUN pip install solc-select
RUN solc-select install 0.8.20
RUN solc-select use 0.8.20
RUN solc --version

# Install Hardhat globally
# RUN npm install -g hardhat

# Verify installation
RUN node -v && npm -v

# Install Foundry (includes forge, cast, anvil)
RUN curl -L https://foundry.paradigm.xyz | bash \
    && /root/.foundry/bin/foundryup

# Add Foundry to PATH
ENV PATH="/root/.foundry/bin:${PATH}"

# Create SSH directory and set permissions
RUN mkdir -p /root/.ssh

# Configure SSH to use the provided key
COPY ilumina /root/.ssh/id_ed25519
COPY ilumina.pub /root/.ssh/id_ed25519.pub
RUN chmod 600 /root/.ssh/id_ed25519 && \
    chmod 644 /root/.ssh/id_ed25519.pub

RUN echo "Host github.com\n\tIdentityFile ~/.ssh/id_ed25519" >> /root/.ssh/config
RUN chmod 644 /root/.ssh/config
RUN chmod 700 /root/.ssh

RUN git config --global user.email  "agent@ilumina.dev"
RUN git config --global user.name  "ilumina"

# Create directory for workspace
RUN mkdir /tmp/workspaces

# Set working directory
WORKDIR /app

# --- 🔒 SECURE REPO CLONING ---
# Clone using build-time SSH mount (keys never enter image)
#RUN --mount=type=ssh \
#    git clone git@github.com:svylabs/ilumina.git /tmp/workspaces/ilumina && \
#    git -C /tmp/workspaces/ilumina config --global --add safe.directory /tmp/workspaces/ilumina

# Copy the .env file into the container
COPY .env /app/.env

# Copy project files (if needed)
# COPY . /app
COPY . .

# Create virtual environment

# Set PATH to use virtualenv packages
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python3 -m venv venv && \
    . venv/bin/activate

RUN pip install --upgrade pip

# Install Python dependencies
RUN pip install -r requirements.txt

# Install Node.js dependencies (if using a frontend or API)
#RUN cd frontend && npm install || true

# Copy supervisord config (to manage multiple processes)
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN which gunicorn
RUN gunicorn --version
# Verify gunicorn is installed


# Expose the required port (Google App Engine listens on 8080)
EXPOSE 8080

# Start services using supervisord
# CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
#CMD ["/bin/bash", "-c", ". /app/.env && . venv/bin/activate && venv/bin/gunicorn -b 0.0.0.0:8080 main:app --timeout 300"]
CMD ["./scripts/entrypoint.sh"]