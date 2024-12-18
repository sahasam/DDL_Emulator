#!/bin/zsh
docker build -t hermes:1.0 .

docker context create mac-remote --docker "host=ssh://srmunamala@169.254.103.200"
docker context create local --docker "host=unix://${HOME}/.colima/default/docker.sock"

docker --context mac-remote stop hermes || true
docker --context mac-remote rm hermes || true
docker --context mac-remote run \
    --name hermes \
    --network host \
    --restart unless-stopped \
    -v ~/.config/hermes:/deploy \
    hermes:1.0


docker --context local stop hermes || true
docker --context local rm hermes || true
docker --context local run \
    --name hermes \
    --network host \
    --restart unless-stopped \
    -v ~/.config/hermes:/deploy \
    hermes:1.0