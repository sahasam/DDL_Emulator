#!/bin/bash

# Get the current username (you could replace this with a specific user if needed)
USER_NAME=$(whoami)

# Define the path to the plist template
PLIST_TEMPLATE="/Users/$USER_NAME/dev/DDL_Emulator/com.daedaelus.hermes.plist"

# Define the path where the plist file will be installed
INSTALL_PATH="/Library/LaunchDaemons/com.daedaelus.hermes.plist"

# Substitute the username in the plist template
sed "s|<USERNAME>|$USER_NAME|g" "$PLIST_TEMPLATE" | sudo tee "$INSTALL_PATH" > /dev/null

# Set proper permissions (launch daemons typically need root permission)
sudo chown root:wheel "$INSTALL_PATH"
sudo chmod 644 "$INSTALL_PATH"

echo "Launch daemon installed at $INSTALL_PATH"