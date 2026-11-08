/*
  LÓT GIÀY THẬT, GỬI QUA DÂY USB (chưa có LoRa)

  Mạch BME3 (ESP32 + 6 FSR) đóng gói HELLO / DATA / ALARM đúng docs/protocol.md
  rồi in ra cổng USB y như ESP32 cầu nối in một gói LoRa vừa nhận:
      RX <hex> -30 10.0
  Gateway gửi ACK xuống bằng dòng "TX <hex>", sketch kiểm tra ACK (đúng node, đúng
  fcnt, đúng MIC) và làm lệnh trong ACK. Như vậy gateway coi lót giày thật là node 1,
  giống hệt khi có LoRa. Sau này gắn Ra-02 thì chỉ thay chỗ in "RX ..." bằng phát LoRa.

  Cách dùng:
    1. Chép node_a/iomt_packet.h vào thư mục này (cạnh file .ino).
    2. Sửa FSR_PINS theo kết quả sketch fsr_pin_scan.
    3. Board "ESP32 Dev Module", Upload. Mở Serial Monitor 115200 xem thử: phải thấy
       dòng "# F ..." mỗi giây và dòng "RX ..." mỗi 15 giây. Xem xong ĐÓNG Serial
       Monitor, vì gateway cần cổng COM này.
    4. Chạy demo: python sim\chay_demo.py --lot-giay-that COM7   (COM theo Device Manager)

  Nút BOOT (GPIO0) trên ESP32: bấm 1 lần = gửi ngay 1 gói ALARM có cờ ngã, để demo
  báo động khi chưa có MPU6050.
*/
#include <Arduino.h>
#include "iomt_packet.h"

// ----------------------------------------------------------------- cấu hình
// Thứ tự giống BME3: gót T, má trong T, má ngoài T, gót P, má trong P, má ngoài P.
// SỬA theo kết quả fsr_pin_scan.
const int FSR_PINS[6] = {36, 39, 34, 35, 32, 33};

const uint8_t NODE_ID = 1;
// KHÓA THỬ của node 1, khớp gateway/config.example.toml. Khóa thật thì lấy từ keys.h.
const uint8_t KEY[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
const uint8_t FW_VERSION = 2;

uint32_t periodS = 15;          // giây giữa 2 gói DATA. chay_demo dùng 15; config.example dùng 60
const uint32_t SAMPLE_MS = 20;  // đọc FSR 50 lần/giây
const int NO_LOAD = 300;        // tổng 6 kênh dưới mức này = không ai mang giày (thang 0..6*4095)
const int HEEL_ON = 1500;       // gót vượt mức này = gót chạm đất (đếm bước)
const int HEEL_OFF = 600;       // gót xuống dưới mức này = gót nhấc lên
const int BOOT_BTN = 0;
const int LED = 2;

const uint32_t ACK_WAIT_MS = 800;
const int MAX_TRIES = 3;

// ----------------------------------------------------------------- khai báo trước
void sampleFsr();
void buildAndQueue(bool alarm);
void startSend(const uint8_t* fr, int len, uint16_t fcnt);
void transmit();
void handleLine(const char* line);
void handleAck(const iomt_ack_t& ack);
int hexToBytes(const char* hex, uint8_t* out, int maxLen);
void printHex(const uint8_t* b, int n);

// ----------------------------------------------------------------- số liệu trong 1 chu kỳ
uint32_t nSamples = 0;
uint64_t sumL = 0, sumR = 0, sumHeel = 0;
uint32_t sumShare = 0, sumShare2 = 0, nShare = 0;
uint16_t steps = 0;
bool heelDown[2] = {false, false};
uint16_t stepsAtPeriodStart = 0;
uint16_t last[6];

// ----------------------------------------------------------------- gửi / chờ ACK
enum State { IDLE, WAIT_ACK, BACKOFF };
State state = IDLE;
uint8_t txFrame[IOMT_DATA_LEN];
int txLen = 0;
uint16_t txFcnt = 0;
int tries = 0;
uint32_t deadline = 0;
bool joined = false;       // đã có ACK cho HELLO
uint16_t fcnt = 0;
bool cmdDone = false;
bool alarmQueued = false;

char lineBuf[96];
int lineLen = 0;
uint32_t lastSample = 0, lastPeriod = 0, lastPrint = 0, ledOffAt = 0;
int blinkLeft = 0;

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  pinMode(LED, OUTPUT);
  analogReadResolution(12);
  for (int i = 0; i < 6; i++) analogSetPinAttenuation(FSR_PINS[i], ADC_11db);

  Serial.printf("# lot giay USB, node %u, fw %u, chu ky %lu s\n", NODE_ID, FW_VERSION,
                (unsigned long)periodS);
  Serial.println(iomt_selftest() ? "# iomt_packet selftest OK" : "# iomt_packet selftest SAI");

  uint8_t hello[IOMT_HELLO_LEN];
  iomt_build_hello(hello, KEY, NODE_ID, esp_random(), FW_VERSION);
  startSend(hello, IOMT_HELLO_LEN, 0);
  lastPeriod = millis();
}

void loop() {
  uint32_t now = millis();

  // 1. đọc FSR đều 50 Hz
  if (now - lastSample >= SAMPLE_MS) {
    lastSample += SAMPLE_MS;
    sampleFsr();
  }

  // 2. đọc dòng từ gateway
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = 0;
        handleLine(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < (int)sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }

  // 3. nút BOOT = báo ngã (chống dội đơn giản)
  static bool btnPrev = true;
  static uint32_t btnAt = 0;
  bool btn = digitalRead(BOOT_BTN);
  if (!btn && btnPrev && now - btnAt > 500) {
    btnAt = now;
    alarmQueued = true;
    Serial.println("# nut BOOT: gui ALARM nga");
  }
  btnPrev = btn;

  // 4. máy trạng thái gửi
  if (state == WAIT_ACK && (int32_t)(now - deadline) >= 0) {
    if (tries >= MAX_TRIES) {
      Serial.printf("# khong co ACK cho fcnt %u sau %d lan, bo goi nay\n", txFcnt, tries);
      state = IDLE;
    } else {
      state = BACKOFF;
      deadline = now + random(500, 2000) * tries;   // 0,5-2 s x số lần đã thử
    }
  }
  if (state == BACKOFF && (int32_t)(now - deadline) >= 0) transmit();

  if (state == IDLE) {
    if (!joined) {
      // chưa vào mạng (gateway chưa chạy lúc bật): 5 s gửi HELLO mới một lần
      if (now - lastPeriod >= 5000) {
        lastPeriod = now;
        uint8_t hello[IOMT_HELLO_LEN];
        iomt_build_hello(hello, KEY, NODE_ID, esp_random(), FW_VERSION);
        startSend(hello, IOMT_HELLO_LEN, 0);
      }
    } else if (alarmQueued) {
      alarmQueued = false;
      buildAndQueue(true);
    } else if (now - lastPeriod >= periodS * 1000) {
      lastPeriod = now;
      buildAndQueue(false);
    }
  }

  // 5. in số đọc mỗi giây để xem bằng Serial Monitor (gateway bỏ qua dòng "#")
  if (now - lastPrint >= 1000) {
    lastPrint = now;
    Serial.printf("# F %u %u %u | %u %u %u  buoc %u\n", last[0], last[1], last[2], last[3],
                  last[4], last[5], steps);
  }

  // 6. nháy LED theo lệnh LED_BLINK
  if (blinkLeft > 0 && (int32_t)(now - ledOffAt) >= 0) {
    digitalWrite(LED, !digitalRead(LED));
    if (!digitalRead(LED)) blinkLeft--;
    ledOffAt = now + 200;
  }
}

void sampleFsr() {
  for (int i = 0; i < 6; i++) last[i] = analogRead(FSR_PINS[i]);
  uint32_t L = last[0] + last[1] + last[2];
  uint32_t R = last[3] + last[4] + last[5];
  sumL += L;
  sumR += R;
  sumHeel += last[0] + last[3];
  nSamples++;
  if (L + R > NO_LOAD) {
    uint32_t share = L * 100 / (L + R);
    sumShare += share;
    sumShare2 += share * share;
    nShare++;
  }
  // đếm bước: mỗi lần gót (trái hoặc phải) chạm đất là 1 bước
  for (int f = 0; f < 2; f++) {
    uint16_t heel = last[f * 3];
    if (!heelDown[f] && heel > HEEL_ON) {
      heelDown[f] = true;
      steps++;
    } else if (heelDown[f] && heel < HEEL_OFF) {
      heelDown[f] = false;
    }
  }
}

void buildAndQueue(bool alarm) {
  iomt_summary_t s;
  memset(&s, 0, sizeof(s));
  uint32_t n = nSamples ? nSamples : 1;
  uint32_t avgL = sumL / n, avgR = sumR / n, avgHeel = sumHeel / n;
  uint32_t total = avgL + avgR;
  uint16_t stepsThis = steps - stepsAtPeriodStart;

  s.flags = (alarm ? IOMT_FLAG_FALL : 0) | (cmdDone ? IOMT_FLAG_CMD_DONE : 0);
  if (total < NO_LOAD) s.activity = IOMT_ACT_NO_LOAD;
  else if (stepsThis >= 2) s.activity = IOMT_ACT_WALKING;
  else s.activity = IOMT_ACT_STANDING;
  s.steps = steps;
  s.load_left = min<uint32_t>(255, avgL * 255 / (3 * 4095));
  s.load_right = min<uint32_t>(255, avgR * 255 / (3 * 4095));
  s.left_share = total > NO_LOAD ? avgL * 100 / total : 50;
  s.heel_share = total > NO_LOAD ? avgHeel * 100 / total : 0;
  if (nShare > 1) {      // sway = độ lệch chuẩn của % lực chân trái trong chu kỳ
    float m = (float)sumShare / nShare;
    float var = (float)sumShare2 / nShare - m * m;
    s.sway = var > 0 ? min(255.0f, sqrtf(var)) : 0;
  }
  s.peak_acc = 0;        // chưa có MPU6050
  s.battery = 100;       // cấp nguồn USB

  fcnt++;
  uint8_t fr[IOMT_DATA_LEN];
  iomt_build_data(fr, KEY, NODE_ID, fcnt, &s, alarm);
  Serial.printf("# %s fcnt %u: trai %lu phai %lu, chan trai %u%%, got %u%%, buoc %u\n",
                alarm ? "ALARM" : "DATA", fcnt, (unsigned long)avgL, (unsigned long)avgR,
                s.left_share, s.heel_share, steps);
  cmdDone = false;
  startSend(fr, IOMT_DATA_LEN, fcnt);

  sumL = sumR = sumHeel = 0;
  sumShare = sumShare2 = nShare = 0;
  nSamples = 0;
  stepsAtPeriodStart = steps;
}

void startSend(const uint8_t* fr, int len, uint16_t f) {
  memcpy(txFrame, fr, len);
  txLen = len;
  txFcnt = f;
  tries = 0;
  transmit();
}

// Gửi lại thì gửi y nguyên gói cũ, cùng fcnt (docs/protocol.md mục 1).
void transmit() {
  tries++;
  Serial.print("RX ");
  printHex(txFrame, txLen);
  Serial.println(" -30 10.0");
  state = WAIT_ACK;
  deadline = millis() + ACK_WAIT_MS;
}

void handleLine(const char* line) {
  if (strncmp(line, "TX ", 3) != 0) return;
  uint8_t fr[32];
  int n = hexToBytes(line + 3, fr, sizeof(fr));
  Serial.println(n > 0 ? "TXOK" : "TXERR hex");
  if (n <= 0 || state != WAIT_ACK) return;
  iomt_ack_t ack;
  if (iomt_parse_ack(fr, n, KEY, NODE_ID, txFcnt, &ack)) handleAck(ack);
}

void handleAck(const iomt_ack_t& ack) {
  state = IDLE;
  if (txFrame[0] == IOMT_HELLO) {
    joined = true;
    lastPeriod = millis();
    Serial.println("# HELLO co ACK, da vao mang");
  }
  if (ack.cmd == IOMT_CMD_NONE) return;
  Serial.printf("# lenh %u arg %u\n", ack.cmd, ack.arg);
  if (ack.cmd == IOMT_CMD_SET_PERIOD && ack.arg > 0) periodS = ack.arg;
  if (ack.cmd == IOMT_CMD_LED_BLINK || ack.cmd == IOMT_CMD_BUZZER_ON) blinkLeft = ack.arg ? ack.arg : 5;
  if (ack.cmd == IOMT_CMD_BUZZER_OFF) {
    blinkLeft = 0;
    digitalWrite(LED, LOW);
  }
  cmdDone = true;
}

int hexToBytes(const char* hex, uint8_t* out, int maxLen) {
  int n = 0;
  while (hex[0] && hex[1]) {
    if (n >= maxLen) return -1;
    char b[3] = {hex[0], hex[1], 0};
    char* end;
    long v = strtol(b, &end, 16);
    if (*end) return -1;
    out[n++] = (uint8_t)v;
    hex += 2;
  }
  return hex[0] ? -1 : n;
}

void printHex(const uint8_t* b, int n) {
  for (int i = 0; i < n; i++) Serial.printf("%02X", b[i]);
}
