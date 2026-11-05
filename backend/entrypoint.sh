#!/bin/sh
# Runs the command as the owner of the models folder, which Compose mounts
# from the host's backend/models. Speech models the app downloads there then
# belong to the host user, not to root or a user only the container knows.
# Without a mounted folder, it runs as the image's unprivileged user.
set -eu

models=/app/models

if [ "$(id -u)" -ne 0 ]; then
    exec "$@"
fi

user=10001
group=10001
if [ -d "$models" ] && [ "$(stat -c %u "$models")" -ne 0 ]; then
    user=$(stat -c %u "$models")
    group=$(stat -c %g "$models")
fi

# The host user has no home in the container
HOME=/tmp exec setpriv --reuid="$user" --regid="$group" --clear-groups -- "$@"
