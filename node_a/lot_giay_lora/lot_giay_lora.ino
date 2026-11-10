/*
  LÓT GIÀY QUA LoRa (node A) - ESP32 + 6 FSR + Ra-02 (SX1278 433 MHz), MPU6050 tùy chọn.

  Việc sketch này làm (đúng docs/protocol.md):
    - Đọc 6 cảm biến lực 200 lần/giây bằng một tác vụ FreeRTOS riêng (nhịp đều 5 ms).
    - Tự tính đặc trưng dáng đi (gait.h), mỗi chu kỳ gói thành 1 gói DATA 19 byte có MIC.
    - Mỗi lần khởi động gửi HELLO, có ACK rồi mới gửi DATA.
    - Phát xong nghe ACK 800 ms; không có thì gửi lại y nguyên gói cũ, tối đa 3 lần.
    - Ba cách dùng kênh: free / tdma / poll (chọn ở cau_hinh.h, phải giống gateway).
    - Làm lệnh gateway gửi kèm trong ACK (còi, nháy LED, đổi chu kỳ), rồi báo CMD_DONE.
    - Nút BOOT hoặc MPU6050 phát hiện ngã thì gửi ALARM.

  Chuẩn bị:
    1. Chép node_a/iomt_packet.h vào thư mục này (cạnh file .ino).
    2. Sửa cau_hinh.h nếu cần (NODE_ID, chế độ kênh, thứ tự chân FSR).
    3. Thư viện RadioLib bản 7.8.1. Board "ESP32 Dev Module", core esp32 3.x.
    4. Nối Ra-02: 3.3V-3V3, GND-GND, NSS-5, SCK-18, MISO-19, MOSI-23, RST-14, DIO0-26.

  !!! LUÔN GẮN ANTEN TRƯỚC KHI CẤP ĐIỆN, phát không anten sẽ hỏng Ra-02 !!!

  Đã biên dịch được (core esp32 3.3.12 + RadioLib 7.8.1). Phần tính dáng đi và phát hiện
  ngã đã thử trên máy tính (node_a/test_gait_host.c). CHƯA CHẠY TRÊN MẠCH THẬT: lần nạp
  đầu mở Serial Monitor 115200, mọi dòng ghi chú bắt đầu bằng "#".
*/
#include <Arduino.h>
#include <RadioLib.h>
#include "cau_hinh.h"
#include "iomt_packet.h"
#include "gait.h"
#if USE_KEYS_H
#include "keys.h"
#endif
#if HAS_MPU6050
#include <Wire.h>
#include "fall.h"
#endif

// ----------------------------------------------------------------- hằng số giao thức
const uint32_t ACK_WAIT_MS = 800;
const int MAX_TRIES = 3;
const uint32_t GUARD_MS = 30;          // chờ thêm đầu khe để bù lệch đồng hồ
// thời gian cần để phát DATA + nhận ACK ở SF7 (52 + 42 ms) cộng 100 ms dự phòng
const uint32_t NEEDED_MS = 200;

// ----------------------------------------------------------------- khai báo trước
// Khai báo trước MỌI hàm, giống hệt dòng định nghĩa, để Arduino không phải tự sinh prototype.
void onDio0(void);
void setup();
void loop();
void halt(const char* what, int16_t code);
void check(const char* what, int16_t code);
void samplerTask(void* arg);
void service();
void waitUntil(uint32_t t);
void waitMs(uint32_t ms);
void startRx();
int rxWait(uint8_t* buf, size_t cap, uint32_t untilMs, uint32_t* tRx);
bool sendOnce(const uint8_t* fr, int len, uint16_t f);
bool sendReliable(const uint8_t* fr, int len, uint16_t f, bool hasDeadline, uint32_t deadline);
void handleAck(const iomt_ack_t& ack);
int buildHello(uint8_t* out);
uint16_t buildData(uint8_t* out, bool alarm);
void runFree();
void runTdma();
void runPoll();
uint32_t slotStart(uint32_t tRx, uint16_t slotMs, int k);
bool tryAlarmThisCycle(uint32_t tRx, const iomt_beacon_t& b, uint8_t* alarmFr, uint16_t* alarmFcnt);
#if HAS_MPU6050
bool mpuBegin();
bool mpuRead(int32_t* ax, int32_t* ay, int32_t* az);
#endif

// ----------------------------------------------------------------- biến chung
SX1278 radio = new Module(PIN_NSS, PIN_DIO0, PIN_RST, RADIOLIB_NC);

volatile bool rxFlag = false;
volatile uint32_t rxAtMs = 0;

const uint8_t* myKey = nullptr;
const uint8_t* netKey = nullptr;
uint8_t mySlot = MY_SLOT;

SemaphoreHandle_t gaitLock;
gait_t gait;                       // chỉ đụng tới khi đang giữ gaitLock
uint16_t lastFsr[6];               // số đọc gần nhất, để in
volatile bool alarmQueued = false; // nút bấm hoặc MPU6050 đặt, vòng chính gửi ALARM
volatile uint8_t peakAcc = 0;      // 0,1 g, lớn nhất trong chu kỳ (MPU6050)
volatile bool mpuOk = false;

uint16_t fcnt = 0;                 // DATA đếm từ 1
uint32_t periodS = DEFAULT_PERIOD_S;
uint32_t lastDataMs = 0;
bool cmdDone = false;

// còi / LED theo lệnh
uint32_t buzzerOffAt = 0;          // 0 = không hẹn giờ
bool buzzerOn = false;
int blinkLeft = 0;
uint32_t blinkAt = 0;

// ----------------------------------------------------------------- ngắt DIO0
void IRAM_ATTR onDio0(void) {
  rxAtMs = millis();
  rxFlag = true;
}

void halt(const char* what, int16_t code) {
  while (true) {
    Serial.printf("# LOI %s ma %d (kiem tra day noi Ra-02, nguon 3.3V)\n", what, code);
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
    delay(2000);
  }
}

void check(const char* what, int16_t code) {
  if (code != RADIOLIB_ERR_NONE) halt(what, code);
}

// ================================================================= setup
void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  if (PIN_BUZZER >= 0) pinMode(PIN_BUZZER, OUTPUT);

#if USE_KEYS_H
  netKey = NET_KEY;
  for (int i = 0; i < NODE_KEY_COUNT; i++) {
    if (NODE_KEYS[i].id == NODE_ID) {
      myKey = NODE_KEYS[i].key;
      if (NODE_KEYS[i].slot) mySlot = NODE_KEYS[i].slot;
    }
  }
  if (myKey == nullptr) halt("NODE_ID khong co trong keys.h", NODE_ID);
#else
  myKey = KEY;
  netKey = NET_KEY;
#endif

  Serial.printf("# lot giay LoRa, node %u, fw %u, khe %u, che do %s, chu ky %lu s, %d mau/giay\n",
                NODE_ID, FW_VERSION, mySlot,
                CHANNEL_MODE == MODE_TDMA ? "tdma" : CHANNEL_MODE == MODE_POLL ? "poll" : "free",
                (unsigned long)periodS, SAMPLE_HZ);
  Serial.println(iomt_selftest() ? "# iomt_packet selftest OK" : "# iomt_packet selftest SAI - bao TV2");

  analogReadResolution(12);
  for (int i = 0; i < 6; i++) analogSetPinAttenuation(FSR_PINS[i], ADC_11db);

#if HAS_MPU6050
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  mpuOk = mpuBegin();
  Serial.println(mpuOk ? "# MPU6050 OK" : "# MPU6050 KHONG THAY (kiem tra SDA 21, SCL 22, nguon)");
#endif

  check("begin", radio.begin());
  check("freq", radio.setFrequency(LORA_FREQ_MHZ));
  check("bw", radio.setBandwidth(LORA_BW_KHZ));
  check("sf", radio.setSpreadingFactor(LORA_SF));
  check("cr", radio.setCodingRate(LORA_CR));
  check("sync", radio.setSyncWord(LORA_SYNC_WORD));
  check("power", radio.setOutputPower(LORA_POWER_DBM));
  check("preamble", radio.setPreambleLength(LORA_PREAMBLE));
  check("crc", radio.setCRC(true));
  radio.setPacketReceivedAction(onDio0);
  startRx();
  Serial.println("# radio OK");

  gaitLock = xSemaphoreCreateMutex();
  gait_init(&gait, SAMPLE_HZ);
  // Tác vụ lấy mẫu chạy ở nhân 0, ưu tiên cao hơn vòng chính (nhân 1 lo radio),
  // nên lúc đang phát LoRa (chặn ~50 ms) nhịp lấy mẫu vẫn đều.
  xTaskCreatePinnedToCore(samplerTask, "fsr", 4096, nullptr, 3, nullptr, 0);

  randomSeed(esp_random());
  lastDataMs = millis();
}

void loop() {
#if CHANNEL_MODE == MODE_TDMA
  runTdma();
#elif CHANNEL_MODE == MODE_POLL
  runPoll();
#else
  runFree();
#endif
}

// ================================================================= lấy mẫu (nhân 0)
void samplerTask(void* arg) {
  (void)arg;
  const TickType_t period = pdMS_TO_TICKS(1000 / SAMPLE_HZ);
  TickType_t last = xTaskGetTickCount();
#if HAS_MPU6050
  fall_t fall;
  fall_init(&fall);
  const int accEvery = SAMPLE_HZ / FALL_FS;   // đọc gia tốc 50 lần/giây
  int accTick = 0;
#endif
  for (;;) {
    vTaskDelayUntil(&last, period);            // nhịp đều, không trôi
    uint16_t v[6];
    for (int i = 0; i < 6; i++) v[i] = analogRead(FSR_PINS[i]);
    xSemaphoreTake(gaitLock, portMAX_DELAY);
    gait_sample(&gait, v);
    memcpy(lastFsr, v, sizeof(v));
    xSemaphoreGive(gaitLock);

#if HAS_MPU6050
    if (mpuOk && ++accTick >= accEvery) {
      accTick = 0;
      int32_t ax, ay, az;
      if (mpuRead(&ax, &ay, &az)) {
        if (fall_feed(&fall, ax, ay, az)) alarmQueued = true;
        uint8_t p = fall_take_peak(&fall);
        if (p > peakAcc) peakAcc = p;
      }
    }
#endif
  }
}

// ================================================================= việc vặt, gọi liên tục khi chờ
void service() {
  uint32_t now = millis();

  // nút BOOT = báo ngã (chống dội)
  static bool btnPrev = true;
  static uint32_t btnAt = 0;
  bool btn = digitalRead(PIN_BUTTON);
  if (!btn && btnPrev && now - btnAt > 500) {
    btnAt = now;
    alarmQueued = true;
    Serial.println("# nut BOOT: se gui ALARM");
  }
  btnPrev = btn;

  // còi hẹn giờ
  if (buzzerOn && buzzerOffAt != 0 && (int32_t)(now - buzzerOffAt) >= 0) {
    buzzerOn = false;
    buzzerOffAt = 0;
    if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, LOW);
    digitalWrite(PIN_LED, LOW);
  }
  // nháy LED theo lệnh
  if (blinkLeft > 0 && (int32_t)(now - blinkAt) >= 0) {
    bool on = !digitalRead(PIN_LED);
    digitalWrite(PIN_LED, on);
    if (!on) blinkLeft--;
    blinkAt = now + 200;
  }

#if DEBUG_PRINT
  static uint32_t lastPrint = 0;
  if (now - lastPrint >= 1000) {
    lastPrint = now;
    uint16_t v[6];
    uint16_t steps;
    uint32_t n;
    xSemaphoreTake(gaitLock, portMAX_DELAY);
    memcpy(v, lastFsr, sizeof(v));
    steps = gait.steps;
    n = gait.n;
    xSemaphoreGive(gaitLock);
    Serial.printf("# F %u %u %u | %u %u %u  buoc %u  mau %lu\n", v[0], v[1], v[2], v[3], v[4],
                  v[5], steps, (unsigned long)n);
  }
#endif
}

void waitUntil(uint32_t t) {
  while ((int32_t)(t - millis()) > 0) {
    service();
    delay(1);
  }
}

void waitMs(uint32_t ms) { waitUntil(millis() + ms); }

// ================================================================= radio
void startRx() {
  rxFlag = false;
  int16_t st = radio.startReceive();
  if (st != RADIOLIB_ERR_NONE) Serial.printf("# startReceive loi %d\n", st);
}

// Chờ 1 gói tới trước thời điểm untilMs. Trả độ dài gói (0 = hết giờ).
// *tRx = lúc nhận xong gói (theo millis), dùng làm mốc t = 0 của beacon.
int rxWait(uint8_t* buf, size_t cap, uint32_t untilMs, uint32_t* tRx) {
  while ((int32_t)(untilMs - millis()) > 0) {
    service();
    if (rxFlag) {
      rxFlag = false;
      uint32_t t = rxAtMs;
      size_t len = radio.getPacketLength();
      if (len > cap) len = cap;
      int16_t st = radio.readData(buf, len);
      startRx();                                // readData đưa module về standby
      if (st == RADIOLIB_ERR_NONE && len > 0) {
        if (tRx) *tRx = t;
        return (int)len;
      }
      // CRC sai: bỏ qua, chờ tiếp
    }
    delay(1);
  }
  return 0;
}

// Phát 1 lần rồi nghe ACK 800 ms. Gói khác (không phải ACK của mình) thì bỏ qua.
bool sendOnce(const uint8_t* fr, int len, uint16_t f) {
  int16_t st = radio.transmit(fr, len);          // chặn tới khi phát xong (~50 ms ở SF7)
  startRx();
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("# phat loi %d\n", st);
    return false;
  }
  uint32_t until = millis() + ACK_WAIT_MS;
  uint8_t buf[32];
  int n;
  while ((n = rxWait(buf, sizeof(buf), until, nullptr)) > 0) {
    iomt_ack_t ack;
    if (iomt_parse_ack(buf, n, myKey, NODE_ID, f, &ack)) {
      Serial.printf("# ACK fcnt %u, rssi %.0f dBm, snr %.1f dB\n", f, radio.getRSSI(), radio.getSNR());
      handleAck(ack);
      return true;
    }
  }
  return false;
}

// Gửi tới khi có ACK, tối đa 3 lần, luôn y nguyên gói cũ (cùng fcnt).
// Có hạn chót (trong khe tdma): chỉ phát nếu còn kịp phát xong và nhận ACK trước hạn; không lùi ngẫu nhiên.
// Không hạn chót (free): giữa các lần chờ ngẫu nhiên 0,5-2 s x số lần đã thử.
bool sendReliable(const uint8_t* fr, int len, uint16_t f, bool hasDeadline, uint32_t deadline) {
  for (int i = 0; i < MAX_TRIES; i++) {
    if (hasDeadline && (int32_t)(deadline - (millis() + NEEDED_MS)) < 0) break;
    if (sendOnce(fr, len, f)) return true;
    if (!hasDeadline && i < MAX_TRIES - 1) waitMs(random(500, 2000) * (i + 1));
  }
  Serial.printf("# khong co ACK cho fcnt %u\n", f);
  return false;
}

void handleAck(const iomt_ack_t& ack) {
  if (ack.cmd == IOMT_CMD_NONE) return;
  Serial.printf("# lenh %u arg %u\n", ack.cmd, ack.arg);
  switch (ack.cmd) {
    case IOMT_CMD_BUZZER_ON:
      buzzerOn = true;
      buzzerOffAt = ack.arg ? millis() + ack.arg * 1000UL : 0;   // 0 = kêu tới khi tắt
      if (buzzerOffAt == 0 && ack.arg) buzzerOffAt = 1;          // tránh trùng giá trị "không hẹn giờ"
      if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, HIGH);
      digitalWrite(PIN_LED, HIGH);
      break;
    case IOMT_CMD_BUZZER_OFF:
      buzzerOn = false;
      buzzerOffAt = 0;
      blinkLeft = 0;
      if (PIN_BUZZER >= 0) digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_LED, LOW);
      break;
    case IOMT_CMD_SET_PERIOD:
      if (ack.arg > 0) periodS = ack.arg;
      break;
    case IOMT_CMD_LED_BLINK:
      blinkLeft = ack.arg ? ack.arg : 5;
      blinkAt = millis();
      break;
    default:
      return;                                    // lệnh lạ: không báo CMD_DONE
  }
  cmdDone = true;
}

// ================================================================= đóng gói
int buildHello(uint8_t* out) {
  return iomt_build_hello(out, myKey, NODE_ID, esp_random(), FW_VERSION);
}

// Lấy đặc trưng của chu kỳ vừa qua, đóng gói DATA hoặc ALARM. Trả fcnt của gói.
uint16_t buildData(uint8_t* out, bool alarm) {
  gait_report_t r;
  xSemaphoreTake(gaitLock, portMAX_DELAY);
  gait_report(&gait, &r);
  xSemaphoreGive(gaitLock);

  iomt_summary_t s;
  memset(&s, 0, sizeof(s));
  s.flags = (alarm ? IOMT_FLAG_FALL : 0) | (cmdDone ? IOMT_FLAG_CMD_DONE : 0) |
            (r.sensor_fault ? IOMT_FLAG_SENSOR_FAULT : 0);
  s.activity = r.activity;
  s.steps = r.steps;
  s.load_left = r.load_left;
  s.load_right = r.load_right;
  s.left_share = r.left_share;
  s.heel_share = r.heel_share;
  s.sway = r.sway;
  s.peak_acc = peakAcc;          // 0 nếu không có MPU6050
  peakAcc = 0;
  s.battery = 100;               // chưa đo pin: mạch chưa có cầu chia áp vào ADC
  cmdDone = false;

  fcnt++;
  if (fcnt == 0) fcnt = 1;       // quay vòng 16 bit: bỏ qua 0 vì 0 dành cho HELLO
  iomt_build_data(out, myKey, NODE_ID, fcnt, &s, alarm ? 1 : 0);
  lastDataMs = millis();
  Serial.printf("# %s fcnt %u: hoat dong %u, buoc %u (+%u), trai %u%%, got %u%%, lac %u, %lu mau\n",
                alarm ? "ALARM" : "DATA", fcnt, r.activity, r.steps, r.steps_in_period,
                r.left_share, r.heel_share, r.sway, (unsigned long)r.samples);
  return fcnt;
}

// ================================================================= chế độ free
void runFree() {
  uint8_t fr[IOMT_DATA_LEN];
  for (;;) {                                     // vào mạng: HELLO tới khi có ACK
    int n = buildHello(fr);
    if (sendReliable(fr, n, 0, false, 0)) break;
    waitMs(random(3000, 8000));
  }
  Serial.println("# HELLO co ACK, da vao mang");
  lastDataMs = millis();
  for (;;) {
    while (!alarmQueued && millis() - lastDataMs < periodS * 1000UL) {
      service();
      delay(1);
    }
    bool alarm = alarmQueued;
    alarmQueued = false;
    uint16_t f = buildData(fr, alarm);
    sendReliable(fr, IOMT_DATA_LEN, f, false, 0);
  }
}

// ================================================================= chế độ tdma
// Mốc t = 0 là lúc nhận xong beacon. Khe k bắt đầu ở k * slot_ms (khe 0 là của beacon).
uint32_t slotStart(uint32_t tRx, uint16_t slotMs, int k) {
  return tRx + (uint32_t)k * slotMs + GUARD_MS;
}

// Báo động xảy ra giữa chu kỳ: nếu còn khe tự do chưa tới thì gửi ngay ở một khe ngẫu nhiên.
// Trả true nếu đã thử gửi (thành công hay không); *alarmFcnt != 0 nghĩa là còn nợ, chu kỳ sau gửi lại.
bool tryAlarmThisCycle(uint32_t tRx, const iomt_beacon_t& b, uint8_t* alarmFr, uint16_t* alarmFcnt) {
  int first = b.n_slots + 1, count = b.free_slots;
  int avail[16], nAvail = 0;
  uint32_t now = millis();
  for (int i = 0; i < count && nAvail < 16; i++) {
    uint32_t start = slotStart(tRx, b.slot_ms, first + i);
    if ((int32_t)(start - now) > 0) avail[nAvail++] = first + i;
  }
  if (nAvail == 0) return false;                 // hết khe tự do: chờ beacon sau
  alarmQueued = false;
  uint16_t f = buildData(alarmFr, true);
  waitUntil(slotStart(tRx, b.slot_ms, avail[random(nAvail)]));
  *alarmFcnt = sendOnce(alarmFr, IOMT_DATA_LEN, f) ? 0 : f;
  return true;
}

void runTdma() {
  bool joined = false;
  bool haveRef = false;
  uint32_t tRx = 0;
  iomt_beacon_t b;
  uint8_t fr[IOMT_DATA_LEN];
  uint8_t alarmFr[IOMT_DATA_LEN];
  uint16_t alarmFcnt = 0;                        // khác 0 = có ALARM chưa được ACK
  uint32_t lastBeaconMs = millis();
  uint32_t lastSendBeacon = 0;                   // mốc beacon của lần gửi DATA gần nhất
  bool sentOnce = false;

  for (;;) {
    // ---- chờ beacon kế tiếp
    for (;;) {
      uint8_t buf[32];
      uint32_t t;
      int n = rxWait(buf, sizeof(buf), millis() + 200, &t);
      if (n > 0 && iomt_parse_beacon(buf, n, netKey, &b)) {
        tRx = t;
        haveRef = true;
        lastBeaconMs = millis();
        break;
      }
      if (alarmQueued && joined && haveRef && alarmFcnt == 0) tryAlarmThisCycle(tRx, b, alarmFr, &alarmFcnt);
      if (millis() - lastBeaconMs > 150000UL) {
        lastBeaconMs = millis();
        Serial.println("# chua nghe thay beacon: gateway co dang chay mode tdma khong?");
      }
    }

    uint32_t end = tRx + (uint32_t)(mySlot + 1) * b.slot_ms;
    if (!joined) {                               // HELLO gửi ở khe riêng
      waitUntil(slotStart(tRx, b.slot_ms, mySlot));
      int n = buildHello(fr);
      joined = sendReliable(fr, n, 0, true, end);
      if (joined) Serial.println("# HELLO co ACK, da vao mang");
      continue;
    }
    if (alarmFcnt != 0) {                        // ALARM còn nợ: gửi lại ở khe riêng, thay cho DATA
      waitUntil(slotStart(tRx, b.slot_ms, mySlot));
      sendReliable(alarmFr, IOMT_DATA_LEN, alarmFcnt, true, end);
      alarmFcnt = 0;
      continue;
    }
    if (alarmQueued) {                           // ALARM mới: thử ở một khe tự do
      if (tryAlarmThisCycle(tRx, b, alarmFr, &alarmFcnt)) continue;
    }
    // Tới lượt gửi chưa: tính theo mốc beacon (không theo lúc phát, vì khe của node có thể nằm
    // giữa chu kỳ). Cho lệch 10% để chu kỳ beacon 60 s khớp chu kỳ gửi 60 s.
    if (sentOnce && tRx - lastSendBeacon < periodS * 900UL) continue;
    lastSendBeacon = tRx;
    sentOnce = true;
    waitUntil(slotStart(tRx, b.slot_ms, mySlot));
    uint16_t f = buildData(fr, false);
    sendReliable(fr, IOMT_DATA_LEN, f, true, end);
  }
}

// ================================================================= chế độ poll
void runPoll() {
  uint8_t fr[IOMT_DATA_LEN];
  waitMs(random(0, 2000));
  for (;;) {
    int n = buildHello(fr);
    if (sendReliable(fr, n, 0, false, 0)) break;
    waitMs(random(3000, 8000));
  }
  Serial.println("# HELLO co ACK, da vao mang");

  bool pending = false;                          // có gói DATA chưa được ACK
  uint16_t pendingFcnt = 0;
  uint16_t lastPollSeq = 0;
  bool seenPoll = false;
  for (;;) {
    if (alarmQueued) {                           // báo động gửi ngay, không chờ được hỏi
      alarmQueued = false;
      uint8_t afr[IOMT_DATA_LEN];
      uint16_t f = buildData(afr, true);
      sendReliable(afr, IOMT_DATA_LEN, f, false, 0);
      pending = false;                           // gói DATA cũ còn nợ có fcnt nhỏ hơn ALARM vừa gửi,
                                                 // gửi nữa sẽ bị gateway chặn (REPLAY): bỏ nó
    }
    uint8_t buf[32];
    int n = rxWait(buf, sizeof(buf), millis() + 200, nullptr);
    uint16_t seq;
    if (n <= 0 || !iomt_parse_poll(buf, n, myKey, NODE_ID, &seq)) continue;
    uint16_t d = (uint16_t)(seq - lastPollSeq);
    if (seenPoll && !(d > 0 && d < 0x8000)) continue;   // POLL cũ phát lại: bỏ
    seenPoll = true;
    lastPollSeq = seq;
    if (!pending) {
      pendingFcnt = buildData(fr, false);
      pending = true;
    }
    delay(10);                                   // cho gateway kịp chuyển từ phát sang nghe
    if (sendOnce(fr, IOMT_DATA_LEN, pendingFcnt)) pending = false;
  }
}

// ================================================================= MPU6050 (tùy chọn)
#if HAS_MPU6050
static const uint8_t MPU_ADDR = 0x68;

bool mpuBegin() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);                              // PWR_MGMT_1: thức dậy
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);                              // ACCEL_CONFIG: thang +-8 g (4096 LSB/g)
  Wire.write(0x10);
  return Wire.endTransmission() == 0;
}

// Gia tốc 3 trục, đơn vị mg.
bool mpuRead(int32_t* ax, int32_t* ay, int32_t* az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU_ADDR, 6) != 6) return false;
  int16_t raw[3];
  for (int i = 0; i < 3; i++) {
    uint8_t hi = Wire.read(), lo = Wire.read();
    raw[i] = (int16_t)((hi << 8) | lo);
  }
  *ax = (int32_t)raw[0] * 1000 / 4096;
  *ay = (int32_t)raw[1] * 1000 / 4096;
  *az = (int32_t)raw[2] * 1000 / 4096;
  return true;
}
#endif
