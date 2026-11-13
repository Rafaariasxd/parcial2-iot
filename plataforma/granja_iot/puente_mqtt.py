import json
import logging

import paho.mqtt.client as mqtt

from .servicio import ErrorDeDatos, NoEncontrado

log = logging.getLogger("granja.mqtt")


class PuenteMqtt:
    def __init__(self, plataforma, host, puerto=1883, usuario=None, clave=None):
        self.plataforma = plataforma
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="plataforma-granja", clean_session=False)
        if usuario:
            self.cliente.username_pw_set(usuario, clave)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_message = self._al_recibir
        self.cliente.reconnect_delay_set(1, 30)
        self.host, self.puerto = host, puerto
        self.conectado = False

    def iniciar(self):
        self.cliente.connect_async(self.host, self.puerto, keepalive=30)
        self.cliente.loop_start()

    def detener(self):
        self.cliente.loop_stop()
        self.cliente.disconnect()

    def publicar(self, topico, carga, retener=False):
        self.cliente.publish(topico, json.dumps(carga, ensure_ascii=False), qos=1, retain=retener)

    def _al_conectar(self, cliente, datos, banderas, codigo, propiedades=None):
        self.conectado = not codigo.is_failure
        if self.conectado:
            for sufijo in ("telemetria", "estado", "conexion", "respuesta"):
                cliente.subscribe(f"granja/+/{sufijo}", qos=1)
            log.info("Conectado al bróker %s:%s", self.host, self.puerto)
        else:
            log.warning("El bróker rechazó la conexión: %s", codigo)

    def _al_recibir(self, cliente, datos, mensaje):
        partes = mensaje.topic.split("/")
        if len(partes) != 3 or not mensaje.payload:
            return
        _, dispositivo, tipo = partes
        try:
            texto = mensaje.payload.decode("utf-8")
            try:
                carga = json.loads(texto)
            except json.JSONDecodeError:
                carga = texto
            if tipo == "telemetria":
                if not isinstance(carga, dict):
                    raise ErrorDeDatos("La telemetría debe ser un objeto JSON")
                valores = carga.get("valores")
                if valores is None:
                    valores = {k: v for k, v in carga.items() if k != "ts"}
                self.plataforma.registrar(dispositivo, valores, carga.get("ts"), via="mqtt")
            elif tipo == "conexion":
                en_linea = carga.get("en_linea") if isinstance(carga, dict) else carga == "en_linea"
                self.plataforma.conexion(dispositivo, bool(en_linea))
            elif tipo == "estado":
                self.plataforma.estado_reportado(dispositivo, carga)
            elif tipo == "respuesta":
                self.plataforma.respuesta(
                    dispositivo, carga.get("comando_id"), bool(carga.get("ok")), carga.get("mensaje", ""),
                    carga.get("estado"),
                )
        except (ErrorDeDatos, NoEncontrado, AttributeError, UnicodeDecodeError) as error:
            log.warning("Mensaje descartado en %s: %s", mensaje.topic, error)
        except Exception:
            log.exception("Error procesando %s", mensaje.topic)
