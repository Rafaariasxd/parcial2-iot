#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <Preferences.h>
#include "secrets.h"

#define PIN_DHT 15
#define PIN_LDR 34
#define PIN_LED 26

const char *ID = "galpon2-ambiente";
const String BASE = String("granja/") + ID;

WiFiClient red;
PubSubClient mqtt(red);
DHT dht(PIN_DHT, DHT22);
Preferences memoria;

bool encendido = true;
bool led = false;
unsigned long intervalo = 30;
float offset[3] = {0, 0, 0};
float factor[3] = {1, 1, 1};
const char *VARIABLES[3] = {"temperatura", "humedad", "luz"};
unsigned long ultimoEnvio = 0;

void cargar() {
  memoria.begin("galpon2", true);
  encendido = memoria.getBool("encendido", true);
  intervalo = memoria.getULong("intervalo", 30);
  for (int i = 0; i < 3; i++) {
    offset[i] = memoria.getFloat((String("o") + i).c_str(), 0);
    factor[i] = memoria.getFloat((String("f") + i).c_str(), 1);
  }
  memoria.end();
}

void guardar() {
  memoria.begin("galpon2", false);
  memoria.putBool("encendido", encendido);
  memoria.putULong("intervalo", intervalo);
  for (int i = 0; i < 3; i++) {
    memoria.putFloat((String("o") + i).c_str(), offset[i]);
    memoria.putFloat((String("f") + i).c_str(), factor[i]);
  }
  memoria.end();
}

void llenarEstado(JsonObject estado) {
  estado["encendido"] = encendido;
  estado["intervalo_s"] = intervalo;
  estado["led"] = led;
  estado["firmware"] = "esp32-galpon2 1.0";
  JsonObject cal = estado["calibracion"].to<JsonObject>();
  for (int i = 0; i < 3; i++) {
    if (offset[i] != 0 || factor[i] != 1) {
      cal[VARIABLES[i]]["offset"] = offset[i];
      cal[VARIABLES[i]]["factor"] = factor[i];
    }
  }
}

void publicarEstado() {
  JsonDocument doc;
  llenarEstado(doc.to<JsonObject>());
  String texto;
  serializeJson(doc, texto);
  mqtt.publish((BASE + "/estado").c_str(), texto.c_str(), true);
}

int indiceVariable(const char *nombre) {
  for (int i = 0; i < 3; i++) {
    if (strcmp(nombre, VARIABLES[i]) == 0) return i;
  }
  return -1;
}

String ejecutar(const char *accion, JsonObject p, bool &ok) {
  ok = true;
  if (strcmp(accion, "apagar") == 0) {
    encendido = false;
    return "Sensor apagado";
  }
  if (strcmp(accion, "encender") == 0) {
    encendido = true;
    return "Sensor encendido";
  }
  if (strcmp(accion, "intervalo") == 0) {
    unsigned long s = p["segundos"] | 0UL;
    if (s < 5 || s > 3600) {
      ok = false;
      return "El intervalo va de 5 a 3600 s";
    }
    intervalo = s;
    return "Intervalo de " + String(s) + " s";
  }
  if (strcmp(accion, "calibrar") == 0) {
    int i = indiceVariable(p["variable"] | "");
    if (i < 0) {
      ok = false;
      return "Variable desconocida";
    }
    offset[i] = p["offset"] | 0.0f;
    factor[i] = p["factor"] | 1.0f;
    return String(VARIABLES[i]) + " calibrada";
  }
  if (strcmp(accion, "reiniciar_calibracion") == 0) {
    for (int i = 0; i < 3; i++) {
      offset[i] = 0;
      factor[i] = 1;
    }
    return "Calibración de fábrica";
  }
  if (strcmp(accion, "led") == 0) {
    led = (p["valor"] | 0) == 1;
    digitalWrite(PIN_LED, led ? HIGH : LOW);
    return led ? "LED de alarma encendido" : "LED de alarma apagado";
  }
  ok = false;
  return String("Acción desconocida: ") + accion;
}

void alRecibir(char *topico, byte *carga, unsigned int largo) {
  if (BASE + "/cmd" != topico) return;
  JsonDocument comando;
  if (deserializeJson(comando, carga, largo)) return;
  const char *accion = comando["accion"] | "";
  if (!*accion) return;
  bool ok;
  String mensaje = ejecutar(accion, comando["parametros"].as<JsonObject>(), ok);
  guardar();
  JsonDocument respuesta;
  respuesta["comando_id"] = comando["id"];
  respuesta["ok"] = ok;
  respuesta["mensaje"] = mensaje;
  llenarEstado(respuesta["estado"].to<JsonObject>());
  String texto;
  serializeJson(respuesta, texto);
  mqtt.publish((BASE + "/respuesta").c_str(), texto.c_str());
  publicarEstado();
  Serial.println("Comando " + String(accion) + ": " + mensaje);
  ultimoEnvio = 0;
}

void conectarWifi() {
  WiFi.begin(WIFI_RED, WIFI_CLAVE, 6);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println(" listo");
}

void conectarMqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT...");
    if (mqtt.connect(ID, MQTT_USUARIO, MQTT_CLAVE, (BASE + "/conexion").c_str(), 1, true, "desconectado")) {
      mqtt.publish((BASE + "/conexion").c_str(), "en_linea", true);
      mqtt.subscribe((BASE + "/cmd").c_str(), 1);
      publicarEstado();
      Serial.println(" conectado");
    } else {
      Serial.println(" falló, estado " + String(mqtt.state()));
      delay(3000);
    }
  }
}

float luxDesdeLdr(int lectura) {
  const float GAMMA = 0.7, RL10 = 50;
  float voltaje = lectura / 4095.0 * 3.3;
  if (voltaje >= 3.29) voltaje = 3.29;
  float resistencia = 2000 * voltaje / (1 - voltaje / 3.3);
  return pow(RL10 * 1e3 * pow(10, GAMMA) / resistencia, 1 / GAMMA);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  analogReadResolution(12);
  dht.begin();
  cargar();
  conectarWifi();
  mqtt.setServer(BROKER_HOST, BROKER_PUERTO);
  mqtt.setBufferSize(1024);
  mqtt.setCallback(alRecibir);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) conectarWifi();
  if (!mqtt.connected()) conectarMqtt();
  mqtt.loop();
  if (!encendido || millis() - ultimoEnvio < intervalo * 1000UL) return;
  ultimoEnvio = millis();
  float crudos[3] = {dht.readTemperature(), dht.readHumidity(), luxDesdeLdr(analogRead(PIN_LDR))};
  JsonDocument doc;
  JsonObject valores = doc["valores"].to<JsonObject>();
  for (int i = 0; i < 3; i++) {
    if (!isnan(crudos[i])) valores[VARIABLES[i]] = crudos[i] * factor[i] + offset[i];
  }
  String texto;
  serializeJson(doc, texto);
  mqtt.publish((BASE + "/telemetria").c_str(), texto.c_str());
  Serial.println(texto);
}
