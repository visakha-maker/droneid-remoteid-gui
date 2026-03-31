from __future__ import annotations

from typing import List, Optional

from paho.mqtt import client as mqtt_client
from PySide6.QtCore import QThread, Signal

import config
from app.parsers.common import iter_json_objects
from app.parsers.remoteid_parser import decode_mqtt_payload, parse_remoteid_row_from_b64, protocol_is_remoteid


class MqttReader(QThread):
    got_payload = Signal(dict)
    got_error = Signal(str)
    got_status = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = False
        self.client: Optional[mqtt_client.Client] = None

    def stop(self):
        self._stop = True
        try:
            if self.client is not None:
                self.client.disconnect()
                self.client.loop_stop()
        except Exception:
            pass

    def run(self):
        try:
            if hasattr(mqtt_client, 'CallbackAPIVersion'):
                self.client = mqtt_client.Client(
                    callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
                    client_id=config.client_id,
                    protocol=mqtt_client.MQTTv311,
                )
            else:
                self.client = mqtt_client.Client(client_id=config.client_id, protocol=mqtt_client.MQTTv311)

            if hasattr(config, 'username'):
                self.client.username_pw_set(config.username, config.password)

            def on_connect(client, userdata, flags, rc, properties=None):
                if rc == 0:
                    self.got_status.emit('Connected to MQTT broker')
                    client.subscribe(config.topic)
                else:
                    self.got_error.emit(f'MQTT connect failed: {rc}')

            def on_message(client, userdata, msg):
                if self._stop:
                    return
                payload = decode_mqtt_payload(msg.payload)
                if not payload:
                    return
                for parsed in iter_json_objects(payload):
                    objs: List[dict] = []
                    if isinstance(parsed, list):
                        objs = [x for x in parsed if isinstance(x, dict)]
                    elif isinstance(parsed, dict):
                        objs = [parsed]
                    for obj in objs:
                        try:
                            if not protocol_is_remoteid(obj.get('protocol')):
                                continue
                            data_json = obj.get('data') or {}
                            uas_b64 = data_json.get('UASdata')
                            if not uas_b64:
                                continue
                            row = parse_remoteid_row_from_b64(uas_b64, data_json)
                            self.got_payload.emit(row.__dict__)
                        except Exception as e:
                            self.got_error.emit(f'MQTT parse error: {e}')

            self.client.on_connect = on_connect
            self.client.on_message = on_message
            self.client.connect(config.broker, config.port)
            self.client.loop_forever()
        except Exception as e:
            self.got_error.emit(str(e))
