# Stage 1: Build the dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2: Build the final image
FROM python:3.11-slim

WORKDIR /app

# Set the path to include the user's local bin directory early
ENV PATH="/home/appuser/.local/bin:${PATH}"

# Create the data directory and ensure correct ownership
RUN mkdir -p /app/data && \
    useradd --create-home appuser && \
    chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Copy the installed dependencies and the application code
COPY --from=builder /wheels /wheels
COPY . /app

# Install the dependencies from the wheelhouse
RUN pip install --no-cache --no-index --find-links=/wheels -r requirements.txt

# Declare a volume for persistent data
VOLUME /app/data

# Expose the port and run the application
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
