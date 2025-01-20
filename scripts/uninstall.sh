#!/bin/bash

# Define paths
USER_HOME="/Users/$USER"
PLIST_DIR="$USER_HOME/Library/LaunchAgents"
PLIST_FILE="com.daedaelus.hermes.plist"
SCRIPT_DIR="$USER_HOME/dev/DDL_Emulator"
SCRIPT_FILE="update_code.sh"
LOGS_DIR="$SCRIPT_DIR/logs"

# Ensure the project directory and logs folder exist
echo "Checking if the logs directory exists..."
mkdir -p "$LOGS_DIR"

# Create the LaunchAgents directory if it doesn't exist
echo "Creating LaunchAgents directory if necessary..."
mkdir -p "$PLIST_DIR"

# Copy the plist file to the LaunchAgents folder
echo "Copying plist file to $PLIST_DIR/$PLIST_FILE"
cp "$SCRIPT_DIR/$PLIST_FILE" "$PLIST_DIR/$PLIST_FILE"

# Copy the update_code.sh script to the project directory
echo "Copying update_code.sh script to $SCRIPT_DIR/$SCRIPT_FILE"
cp "$SCRIPT_DIR/$SCRIPT_FILE" "$SCRIPT_DIR/$SCRIPT_FILE"

# Make sure both the plist and script are executable
echo "Making the update script and plist executable..."
chmod +x "$SCRIPT_DIR/$SCRIPT_FILE"

# Load the plist file (this starts the service immediately)
echo "Loading the LaunchAgent plist to start the service..."
launchctl load "$PLIST_DIR/$PLIST_FILE"

# Confirmation
echo "Installation complete! The service will run at startup and attempt to pull updates from Git."