#!/bin/bash

# Directory of your project
PROJECT_DIR="/opt/hermes"
LOGS_DIR="$PROJECT_DIR/logs"

# Create the logs directory if it doesn't exist
if [ ! -d "$LOGS_DIR" ]; then
  echo "Logs directory doesn't exist. Creating $LOGS_DIR..."
  mkdir "$LOGS_DIR"
fi

# Attempt to pull the latest changes from the repository
echo "Attempting to pull the latest code from Git..."

# Change to the project directory
cd "$PROJECT_DIR" && git pull origin main


# Check if the git pull was successful
if [ $? -eq 0 ]; then
  echo "Git pull successful. Running the latest code..."
else
  echo "Git pull failed (likely due to no internet access). Running the existing code..."
fi

# Run the code (assuming it's a script or app you can execute directly)
# Modify this command as necessary to run your actual application
# ./your_application_or_script.sh  # Modify this line to run your app
$PROJECT_DIR/env/bin/python3 -u $PROJECT_DIR/src/main.py -c $PROJECT_DIR/scripts/prod_config.yml