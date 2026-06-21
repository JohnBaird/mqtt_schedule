#!/usr/bin/env bash
set -euo pipefail

# Installs mqtt_schedule from a user-uploaded staging directory into Linux system paths.
#
# Typical usage:
#   1. Upload repo to /home/john/mqtt_schedule_temp
#   2. Run:
#      sudo bash /home/john/mqtt_schedule_temp/deploy/install_linux.sh /home/john/mqtt_schedule_temp
#
# Result:
#   - Code copied to /opt/mqtt_schedule
#   - Config templates copied to /etc/mqtt_schedule
#   - systemd unit copied to /etc/systemd/system

if [[ $# -lt 1 ]]; then
  echo "Usage: sudo bash deploy/install_linux.sh /path/to/uploaded/mqtt_schedule_repo"
  exit 1
fi

SRC_DIR="$(cd "$1" && pwd)"
APP_DIR="/opt/mqtt_schedule"
ETC_DIR="/etc/mqtt_schedule"
STATE_DIR="/var/lib/mqtt_schedule"
UNIT_SRC="$SRC_DIR/deploy/mqtt_schedule.service"
UNIT_DST="/etc/systemd/system/mqtt_schedule.service"
OPENWEATHER_CURRENT_FILE="$ETC_DIR/ow_records_current.json"
OPENWEATHER_FORECAST_FILE="$ETC_DIR/ow_records_forecast.json"
TEMPEST_DIR="$ETC_DIR/tempest_weather_data"

SERVICE_USER="mqttschedule"
SERVICE_GROUP="mqttschedule"

echo "Source directory: $SRC_DIR"
echo "Install directory: $APP_DIR"
echo "Config directory: $ETC_DIR"
echo "State directory: $STATE_DIR"

if [[ ! -f "$SRC_DIR/pyproject.toml" ]]; then
  echo "ERROR: $SRC_DIR does not look like the mqtt_schedule repo."
  exit 1
fi

mkdir -p "$ETC_DIR"
mkdir -p "$STATE_DIR"

if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
  groupadd --system "$SERVICE_GROUP"
fi

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" \
    --home-dir "$APP_DIR" \
    --shell /usr/sbin/nologin \
    "$SERVICE_USER"
fi

echo "Copying application files..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='__pycache__' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  -C "$SRC_DIR" \
  -cf - . | tar -C "$APP_DIR" -xf -

echo "Creating Python virtual environment..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install .

echo "Installing config templates..."
if [[ ! -f "$ETC_DIR/runtime.json" ]]; then
  cp "$APP_DIR/deploy/runtime.example.json" "$ETC_DIR/runtime.json"
fi

if [[ ! -f "$ETC_DIR/mqtt_schedule.env" ]]; then
  cp "$APP_DIR/deploy/mqtt_schedule.env.example" "$ETC_DIR/mqtt_schedule.env"
fi

mkdir -p "$TEMPEST_DIR"
touch "$OPENWEATHER_CURRENT_FILE" "$OPENWEATHER_FORECAST_FILE"

echo "Installing systemd unit..."
cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload

echo "Setting ownership and permissions..."
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$STATE_DIR"
chown root:"$SERVICE_GROUP" "$ETC_DIR"
chown root:root "$ETC_DIR/runtime.json"
chown root:"$SERVICE_GROUP" "$ETC_DIR/mqtt_schedule.env"
chown "$SERVICE_USER":"$SERVICE_GROUP" "$OPENWEATHER_CURRENT_FILE" "$OPENWEATHER_FORECAST_FILE"
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$TEMPEST_DIR"
chmod 755 "$APP_DIR"
chmod 755 "$APP_DIR/deploy/install_linux.sh"
chmod 755 "$APP_DIR/.venv/bin/python"
chmod 644 "$ETC_DIR/runtime.json"
chmod 640 "$ETC_DIR/mqtt_schedule.env"
chmod 775 "$ETC_DIR"
chmod 664 "$OPENWEATHER_CURRENT_FILE" "$OPENWEATHER_FORECAST_FILE"
chmod 755 "$TEMPEST_DIR"
chmod 755 "$STATE_DIR"

cat <<EOF

Install complete.

Next steps:
1. Edit $ETC_DIR/runtime.json
2. Edit $ETC_DIR/mqtt_schedule.env
3. Copy Airtable/weather files into $ETC_DIR
4. Verify or allow creation of $STATE_DIR/device_serial.txt
5. The installer prepares writable weather outputs for the service at:
   - $OPENWEATHER_CURRENT_FILE
   - $OPENWEATHER_FORECAST_FILE
   - $TEMPEST_DIR
6. Dry-run test:
   $APP_DIR/.venv/bin/python -m mqtt_schedule --config $ETC_DIR/runtime.json --dry-run
7. Start service:
   systemctl enable mqtt_schedule
   systemctl start mqtt_schedule
   systemctl status mqtt_schedule

EOF
