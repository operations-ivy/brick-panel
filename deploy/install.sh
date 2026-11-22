#!/bin/sh
# Set up the neon panel on brick1982. Run on brick1982 itself, from the git
# clone at ~/brick-panel. It installs and doesn't switch: LCARS stays on until
# deploy/panel-select neon. After that, brick-panel-deploy.timer keeps the
# panel up to date from GitHub. Rerun after a change under deploy/.
set -eu
here=$(cd "$(dirname "$0")" && pwd)

# All from Debian (no venv on the Pi): cage is the compositor, wlr-randr turns
# the panel, grim takes screenshots for checking it over ssh.
sudo apt-get install -y --no-install-recommends cage chromium wlr-randr grim \
    python3-yaml python3-pytest

mkdir -p ~/.config/brick-panel ~/.config/systemd/user
if [ ! -f ~/.config/brick-panel/settings.yaml ]; then
    install -m 600 /dev/null ~/.config/brick-panel/settings.yaml
    echo "# This panel's own settings, merged over brick_panel/defaults.yaml." >~/.config/brick-panel/settings.yaml
fi
cp "$here/brick-panel-deploy.service" "$here/brick-panel-deploy.timer" ~/.config/systemd/user/

sudo cp "$here/90-backlight.rules" /etc/udev/rules.d/
sudo udevadm trigger --subsystem-match=backlight --action=add
sudo python3 "$here/blank-cursors" /usr/local/share/brick-panel/cursors/default
sudo cp "$here/brick-panel.service" "$here/brick-panel-kiosk.service" /etc/systemd/system/
sudo install -m 755 "$here/panel-select" /usr/local/bin/panel-select

sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
sudo systemctl daemon-reload
sudo systemctl set-default graphical.target
# Pick up a change to the units if the neon panel is the one in use.
sudo systemctl try-restart brick-panel.service brick-panel-kiosk.service
echo "brick-panel installed. Switch with: panel-select neon (back: panel-select lcars)"
