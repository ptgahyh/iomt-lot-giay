// =====================================================================
// DÒ CHÂN FSR CỦA MẠCH LÓT GIÀY BME3
// ---------------------------------------------------------------------
// Code BME3 cũ chỉ còn trang web (nhận 6 số qua BLE), không còn code
// ESP32 nên không biết FSR nối chân nào. Sketch này đọc mọi chân ADC
// mà ESP32 DevKit có đưa ra ngoài, rồi:
//   - lúc khởi động: đo giá trị nền khi KHÔNG ai ấn cảm biến (3 giây)
//   - sau đó: ấn 1 cảm biến, chân nào tăng mạnh thì in ra tên chân đó
//   - gõ "t" + Enter trong Serial Monitor: in bảng giá trị mọi chân
//   - gõ "b" + Enter: đo lại giá trị nền
//
// Cách dùng: Board "ESP32 Dev Module", Serial Monitor 115200, chọn
// "Newline". Lúc vừa nạp xong, ĐỂ YÊN lót giày 3 giây. Rồi ấn lần lượt
// gót trái, má trong trái, má ngoài trái, gót phải, má trong phải,
// má ngoài phải. Ghi lại chân hiện ra cho từng vị trí.
//
// Không cần tháo module LoRa. Sketch không đụng tới LoRa nên đọc thử
// các chân 14/26/27 (của LoRa) cũng không sao, chỉ cần bỏ qua chúng.
// =====================================================================

#include <Arduino.h>

// Mọi chân có ADC trên ESP32 DevKit (ADC1 trước, ADC2 sau).
// ADC2 vẫn đọc được vì sketch này không bật Wi-Fi.
const int PINS[] = {36, 39, 34, 35, 32, 33,              // ADC1
                    25, 26, 27, 14, 12, 13, 15, 2, 4, 0}; // ADC2
const int N = sizeof(PINS) / sizeof(PINS[0]);

const int JUMP = 400;        // tăng hơn chừng này (thang 0..4095) = "đang bị ấn"
uint16_t base[N];
bool active[N];

void printTable();

uint16_t readAvg(int pin) {
  uint32_t s = 0;
  for (int k = 0; k < 16; k++) s += analogRead(pin);
  return s / 16;
}

void measureBase() {
  Serial.println("# Do gia tri nen, DE YEN lot giay 3 giay...");
  uint32_t sum[N] = {0};
  int rounds = 0;
  uint32_t t0 = millis();
  while (millis() - t0 < 3000) {
    for (int i = 0; i < N; i++) sum[i] += readAvg(PINS[i]);
    rounds++;
    delay(20);
  }
  for (int i = 0; i < N; i++) {
    base[i] = sum[i] / rounds;
    active[i] = false;
  }
  printTable();
  Serial.println("# Xong. Gio an tung cam bien. Chan nen > 300 la dang tha noi (khong noi gi) hoac bi keo len.");
}

void printTable() {
  Serial.println("# chan : nen(0..4095)  dien_ap_uoc_tinh");
  for (int i = 0; i < N; i++) {
    Serial.printf("# GPIO%-2d: %4u  ~%.2f V\n", PINS[i], base[i], base[i] * 3.1f / 4095.0f);
  }
}

void printNow() {
  Serial.println("# chan : bay_gio  nen");
  for (int i = 0; i < N; i++) {
    Serial.printf("# GPIO%-2d: %4u  %4u\n", PINS[i], readAvg(PINS[i]), base[i]);
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("# Do chan FSR cua mach BME3");
  analogReadResolution(12);
  for (int i = 0; i < N; i++) analogSetPinAttenuation(PINS[i], ADC_11db);
  measureBase();
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 't') printNow();
    if (c == 'b') measureBase();
  }

  for (int i = 0; i < N; i++) {
    int v = readAvg(PINS[i]);
    int d = v - (int)base[i];
    if (!active[i] && d > JUMP) {
      active[i] = true;
      Serial.printf(">>> GPIO%d DANG BI AN: nen %u -> %d (~%.2f V)\n",
                    PINS[i], base[i], v, v * 3.1f / 4095.0f);
    } else if (active[i] && d < JUMP / 2) {
      active[i] = false;
      Serial.printf("    GPIO%d nha ra (%d)\n", PINS[i], v);
    }
  }
  delay(50);
}
