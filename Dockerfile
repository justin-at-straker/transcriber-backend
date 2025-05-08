# First build stage - Build venv with pipenv
FROM docker.io/python:3.12-slim-bullseye as builder

RUN pip install --user pipenv

WORKDIR /build

# Tell pipenv to create venv in the current directory
ENV PIPENV_VENV_IN_PROJECT=1
COPY Pipfile Pipfile.lock /build/
RUN /root/.local/bin/pipenv sync


# Final build stage - Run the app
FROM docker.io/python:3.12-slim-bullseye

LABEL maintainer "Straker Group"
LABEL repository "https://github.com/strakergroup/sup-transcriber-api"

# Install ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv from the previous build stage
COPY --from=builder /build/.venv/ /venv/

COPY src src

# Set environment variables
ENV PYTHONPATH=/app

# Do not run with root
RUN useradd -m -u 1001 -g 33 straker
USER straker

# Run the app with environment-aware configuration
CMD ["/venv/bin/python", "-m", "uvicorn", "src.main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "80"]
