/*
  KẸP TAY Wi-Fi/MQTT (node B) - ESP32 + MAX30102.

  Việc sketch này làm (đúng docs/protocol.md mục 8):
    - Đọc MAX30102 ở 25 mẫu/giây (2 kênh đỏ và hồng ngoại), giữ 100 mẫu gần nhất (4 giây).
    - Mỗi chu kỳ (mặc định 5 s) chạy thuật toán của hãng Maxim ra nhịp tim và SpO2, gửi
      iomt/wrist/<id>/telemetry dạng {"fcnt":12,"hr":78,"spo2":97,"finger":true,"batt":85}.
    - Nghe iomt/wrist/<id>/cmd, làm lệnh (còi, nháy LED, đổi chu kỳ), trả iomt/wrist/<id>/ack.
    - Đăng nhập Mosquitto với username = id. Mất Wi-Fi hoặc broker thì tự nối lại.

  Thư viện (Tools > Manage Libraries):
    - "SparkFun MAX3010x Pulse and Proximity Sensor Library" (bản 1.1.2)
    - "PubSubClient" của Nick O'Leary (bản 2.8)
  Board "ESP32 Dev Module", core esp32 3.x.

  Nối dây MAX30102: VIN-3V3, GND-GND, SDA-21, SCL-22.

  Đã biên dịch được (core esp32 3.3.12). Phần tạo và đọc JSON đã thử trên máy tính
  (node_b/test_kep_tay_host.c) và đối chiếu với gateway. CHƯA CHẠY TRÊN MẠCH THẬT.
  Số nhịp tim và SpO2 của MAX30102 là để theo dõi, KHÔNG phải thiết bị y tế.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include "MAX30105.h"
#include "spo2_algorithm.h"
#if __has_include("cau_hinh_rieng.h")
#include "cau_hinh_rieng.h"
#else
#include "cau_hinh.h"
#endif
#include "kep_tay_logic.h"

// Khai báo trước mọi hàm, giống hệt dòng định nghĩa, để Arduino không phải tự sinh prototype.
void setup();
void loop();
void readSensor();
void compute(kt_reading_t* r);
void ensureWifi();
void ensureMqtt();
void onMessage(char* topic, byte* payload, unsigned int len);
void serviceOutputs();

const int N = 100;                 // 100 mẫu = 4 giây ở 25 mẫu/giây (theo thuật toán mẫu của hãng)
uint32_t irBuf[N], redBuf[N];      // 2 x 100 x 4 byte = 800 byte
int filled = 0;                    // số mẫu hợp lệ trong bộ đệm (tối đa N)
uint32_t samplesInPeriod = 0;

MAX30105 sensor;
bool sensorOk = false;
WiFiClient net;
PubSubClient mqtt(net);

char topicTel[48], topicCmd[48], topicAck[48], clientId[24], userName[8];
uint32_t fcnt = 0;
uint32_t periodS = DEFAULT_PERIOD_S;
uint32_t lastSend = 0, lastWifiTry = 0, lastMqttTry = 0;

bool buzzerOn = false;
uint32_t buzzerOffAt = 0;          // 0 = không hẹn giờ
int blinkLeft = 0;
uint32_t blinkAt = 0;

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_LED, OUTPUT);
  if (PIN_BUZZER >= 0) pinMode(PIN_BUZZER, OUTPUT);

  snprintf(topicTel, sizeof(topicTel), "%s/%d/telemetry", TOPIC_PREFIX, NODE_ID);
  snprintf(topicCmd, sizeof(topicCmd), "%s/%d/cmd", TOPIC_PREFIX, NODE_ID);
  snprintf(topicAck, sizeof(topicAck), "%s/%d/ack", TOPIC_PREFIX, NODE_ID);
  snprintf(clientId, sizeof(clientId), "wrist%d", NODE_ID);
  snprintf(userName, sizeof(userName), "%d", NODE_ID);
  Serial.printf("# kep tay MQTT, node %d, chu ky %lu s, broker %s:%d\n", NODE_ID,
                (unsigned long)periodS, MQTT_HOST, MQTT_PORT);

  Wire.begin(PIN_SDA, PIN_SCL);
  sensorOk = sensor.begin(Wire, I2C_SPEED_FAST);
  if (sensorOk) {
    // độ sáng LED 60 (~12 mA), lấy trung bình 4 mẫu, 2 LED (đỏ + hồng ngoại), 100 mẫu/giây
    // -> 25 mẫu/giây sau trung bình; độ rộng xung 411 us (18 bit), thang ADC 4096 nA
    sensor.setup(60, 4, 2, 100, 411, 4096);
    Serial.println("# MAX30102 OK");
  } else {
    Serial.println("# MAX30102 KHONG THAY (kiem tra SDA 21, SCL 22, nguon 3V3). Van chay, gui finger=false");
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
  lastSend = millis();
}

void loop() {
  readSensor();
  ensureWifi();
  ensureMqtt();
  mqtt.loop();
  serviceOutputs();

  uint32_t now = millis();
  if (now - lastSend >= periodS * 1000UL) {
    lastSend = now;
    kt_reading_t r;
    compute(&r);
    char json[96];
    if (kt_telemetry_json(json, sizeof(json), &r) > 0) {
      bool sent = mqtt.connected() && mqtt.publish(topicTel, json);
      Serial.printf("# %s %s (%lu mau)\n", sent ? "gui" : "CHUA NOI, bo", json, (unsigned long)samplesInPeriod);
    }
    samplesInPeriod = 0;
  }
  delay(2);
}

// Lấy mọi mẫu mới từ cảm biến vào bộ đệm trượt (giữ N mẫu gần nhất).
void readSensor() {
  if (!sensorOk) return;
  sensor.check();
  while (sensor.available()) {
    if (filled == N) {
      memmove(irBuf, irBuf + 1, (N - 1) * sizeof(uint32_t));
      memmove(redBuf, redBuf + 1, (N - 1) * sizeof(uint32_t));
      filled = N - 1;
    }
    redBuf[filled] = sensor.getFIFORed();
    irBuf[filled] = sensor.getFIFOIR();
    filled++;
    samplesInPeriod++;
    sensor.nextSample();
  }
}

void compute(kt_reading_t* r) {
  memset(r, 0, sizeof(*r));
  r->fcnt = ++fcnt;
  r->batt = -1;                    // chưa đo pin
  if (!sensorOk || filled < N) return;          // chưa đủ 4 giây dữ liệu: finger = false

  uint64_t sum = 0;
  for (int i = 0; i < N; i++) sum += irBuf[i];
  uint32_t irAvg = (uint32_t)(sum / N);
  r->finger = irAvg >= FINGER_IR_MIN;
  Serial.printf("# ir trung binh %lu\n", (unsigned long)irAvg);
  if (!r->finger) return;

  int32_t spo2, hr;
  int8_t spo2Valid, hrValid;
  maxim_heart_rate_and_oxygen_saturation(irBuf, N, redBuf, &spo2, &spo2Valid, &hr, &hrValid);
  r->hr = hr;
  r->hr_valid = hrValid && kt_hr_plausible(hr);
  r->spo2 = spo2;
  r->spo2_valid = spo2Valid && kt_spo2_plausible(spo2);
}

void ensureWifi() {
  static bool was = false;
  bool up = WiFi.status() == WL_CONNECTED;
  if (up && !was) Serial.printf("# Wi-Fi OK, IP %s, RSSI %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  if (!up && was) Serial.println("# mat Wi-Fi, dang noi lai");
  was = up;
  if (!up && millis() - lastWifiTry > 10000) {  // setAutoReconnect thường đủ; đây là lưới an toàn
    lastWifiTry = millis();
    WiFi.reconnect();
  }
}

void ensureMqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  if (millis() - lastMqttTry < 3000) return;    // thử lại mỗi 3 s, không chặn việc đọc cảm biến lâu
  lastMqttTry = millis();
  bool ok = strlen(MQTT_PASS) ? mqtt.connect(clientId, userName, MQTT_PASS) : mqtt.connect(clientId);
  if (ok) {
    mqtt.subscribe(topicCmd, 1);
    Serial.println("# MQTT OK");
  } else {
    // 4 = sai mật khẩu, 5 = không được phép, -2 = không tới được broker (sai IP, tường lửa)
    Serial.printf("# MQTT loi %d\n", mqtt.state());
  }
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  (void)topic;
  char buf[128];
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, payload, len);
  buf[len] = 0;
  kt_cmd_t c;
  if (!kt_parse_cmd(buf, &c)) {
    Serial.printf("# lenh hong: %s\n", buf);
    return;
  }
  bool ok = true;
  switch (c.cmd) {
    case KT_CMD_BUZZER_ON:
      buzzerOn = true;
      buzzerOffAt = c.arg > 0 ? (millis() + (uint32_t)c.arg * 1000UL) | 1 : 0;   // |1: không trùng 0
      if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, HIGH);
      digitalWrite(PIN_LED, HIGH);
      break;
    case KT_CMD_BUZZER_OFF:
      buzzerOn = false;
      buzzerOffAt = 0;
      blinkLeft = 0;
      if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_LED, LOW);
      break;
    case KT_CMD_SET_PERIOD:
      if (c.arg >= 1 && c.arg <= 3600) periodS = (uint32_t)c.arg;
      else ok = false;
      break;
    case KT_CMD_BLINK:
      blinkLeft = c.arg > 0 ? (int)c.arg : 5;
      blinkAt = millis();
      break;
    default:
      ok = false;
  }
  char ack[40];
  kt_ack_json(ack, sizeof(ack), c.seq, ok);
  mqtt.publish(topicAck, ack);
  Serial.printf("# lenh %s -> %s\n", buf, ack);
}

void serviceOutputs() {
  uint32_t now = millis();
  if (buzzerOn && buzzerOffAt != 0 && (int32_t)(now - buzzerOffAt) >= 0) {
    buzzerOn = false;
    buzzerOffAt = 0;
    if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, LOW);
    digitalWrite(PIN_LED, LOW);
  }
  if (blinkLeft > 0 && (int32_t)(now - blinkAt) >= 0) {
    bool on = !digitalRead(PIN_LED);
    digitalWrite(PIN_LED, on);
    if (!on) blinkLeft--;
    blinkAt = now + 200;
  }
}
