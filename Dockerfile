# Use a lightweight Python base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create a volume for the SQLite database so data persists
VOLUME /app/data

# Environment variable for the database file location
ENV DB_FILE=/app/data/savings_data.db

# Expose the port Flask runs on
EXPOSE 8080

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "app:app"]
