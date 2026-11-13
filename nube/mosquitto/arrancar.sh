#!/bin/sh
set -e
touch /mosquitto/passwd
mosquitto_passwd -b /mosquitto/passwd plataforma "$MQTT_CLAVE_PLATAFORMA"
mosquitto_passwd -b /mosquitto/passwd dispositivos "$MQTT_CLAVE_DISPOSITIVOS"
chown mosquitto:mosquitto /mosquitto/passwd
chmod 0600 /mosquitto/passwd
exec mosquitto -c /mosquitto/config/mosquitto.conf
