/*
  PHÁT THỬ ĐO TẦM XA LoRa (bài T1)

  Mạch phát: ESP32 + Ra-02, chạy pin (ví dụ mạch lót giày), người cầm đi tới từng điểm đo.
  Mạch thu: ESP32 cầu nối của gateway, nạp sẵn gateway/bridge_firmware/lora_bridge, cắm laptop.
  Laptop chạy:  python tools/do_tam_xa/do_tam_xa.py ghi --port COM7

  Cách đo một điểm:
    1. Đứng ở điểm đo, bấm nút BOOT 1 lần.
    2. LED sáng liên tục trong lúc phát. Mạch phát SO_GOI gói, mỗi gói cách nhau KHOANG_MS,
       lần lượt ở từng mức công suất trong CONG_SUAT[] (mặc định chỉ 14 dBm).
    3. LED tắt là xong lượt, đi sang điểm kế tiếp, bấm BOOT lần nữa.
  Mỗi lần bấm là một "lượt" có số thứ tự riêng, ghi lại điểm đo của từng lượt trên giấy.

  Gói phát dài đúng 19 byte như gói DATA thật, để thời gian phát (51,5 ms ở SF7) giống hệt:
    [0x7F][node_id][luot u16][stt u16][cong_suat i8][0x55 x 12]
  Loại 0x7F không có trong giao thức, gateway sẽ không nhầm với gói thật.

  !!! LUÔN GẮN ANTEN TRƯỚC KHI CẤP ĐIỆN !!!
  Chân giống cầu nối và lót giày: NSS 5, DIO0 26, RST 14, SCK 18, MISO 19, MOSI 23.
*/
#include <Arduino.h>
#include <RadioLib.h>

#define PIN_NSS 5
#define PIN_DIO0 26
#define PIN_RST 14
#define PIN_LED 2
#define PIN_BUTTON 0

// Thông số radio: PHẢI GIỐNG cầu nối (docs/protocol.md mục 1)
#define LORA_FREQ_MHZ 433.5
#define LORA_BW_KHZ 125.0
#define LORA_SF 7
#define LORA_CR 5
#define LORA_SYNC_WORD 0x12
#define LORA_PREAMBLE 8

const uint8_t NODE_ID = 1;
const int SO_GOI = 100;              // số gói mỗi mức công suất trong 1 lượt
const uint32_t KHOANG_MS = 300;      // khoảng cách giữa 2 gói
// Thử nhiều mức công suất trong 1 lượt, ví dụ {14, 10, 5, 2}: xem hạ công suất còn đủ không.
const int8_t CONG_SUAT[] = {14};
const int SO_MUC = sizeof(CONG_SUAT) / sizeof(CONG_SUAT[0]);

void setup();
void loop();
void halt(const char* what, int16_t code);
void phatLuot();

SX1278 radio = new Module(PIN_NSS, PIN_DIO0, PIN_RST, RADIOLIB_NC);
uint16_t luot = 0;

void halt(const char* what, int16_t code) {
  while (true) {
    Serial.printf("# LOI %s ma %d (kiem tra day noi Ra-02, nguon 3.3V)\n", what, code);
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
    delay(300);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  int16_t st = radio.begin();
  if (st != RADIOLIB_ERR_NONE) halt("begin", st);
  if ((st = radio.setFrequency(LORA_FREQ_MHZ)) != RADIOLIB_ERR_NONE) halt("freq", st);
  if ((st = radio.setBandwidth(LORA_BW_KHZ)) != RADIOLIB_ERR_NONE) halt("bw", st);
  if ((st = radio.setSpreadingFactor(LORA_SF)) != RADIOLIB_ERR_NONE) halt("sf", st);
  if ((st = radio.setCodingRate(LORA_CR)) != RADIOLIB_ERR_NONE) halt("cr", st);
  if ((st = radio.setSyncWord(LORA_SYNC_WORD)) != RADIOLIB_ERR_NONE) halt("sync", st);
  if ((st = radio.setPreambleLength(LORA_PREAMBLE)) != RADIOLIB_ERR_NONE) halt("preamble", st);
  if ((st = radio.setCRC(true)) != RADIOLIB_ERR_NONE) halt("crc", st);
  Serial.printf("# phat thu do tam xa: %d goi x %d muc cong suat, cach %lu ms. Bam BOOT de bat dau 1 luot\n",
                SO_GOI, SO_MUC, (unsigned long)KHOANG_MS);
  // nháy 3 lần: radio sẵn sàng
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(150);
    digitalWrite(PIN_LED, LOW);
    delay(150);
  }
}

void loop() {
  static bool prev = true;
  bool btn = digitalRead(PIN_BUTTON);
  if (!btn && prev) {
    delay(30);                                  // chống dội
    if (!digitalRead(PIN_BUTTON)) phatLuot();
  }
  prev = btn;
  delay(5);
}

void phatLuot() {
  luot++;
  digitalWrite(PIN_LED, HIGH);
  int loi = 0;
  for (int m = 0; m < SO_MUC; m++) {
    int16_t st = radio.setOutputPower(CONG_SUAT[m]);
    if (st != RADIOLIB_ERR_NONE) halt("power", st);
    Serial.printf("# luot %u, cong suat %d dBm\n", luot, CONG_SUAT[m]);
    for (int i = 0; i < SO_GOI; i++) {
      uint32_t t0 = millis();
      uint8_t p[19];
      memset(p, 0x55, sizeof(p));
      p[0] = 0x7F;
      p[1] = NODE_ID;
      p[2] = luot & 0xFF;
      p[3] = luot >> 8;
      uint16_t stt = m * SO_GOI + i;            // số thứ tự trong lượt, liên tục qua các mức
      p[4] = stt & 0xFF;
      p[5] = stt >> 8;
      p[6] = (uint8_t)CONG_SUAT[m];
      if (radio.transmit(p, sizeof(p)) != RADIOLIB_ERR_NONE) loi++;
      while (millis() - t0 < KHOANG_MS) delay(1);
    }
  }
  digitalWrite(PIN_LED, LOW);
  Serial.printf("# xong luot %u, %d loi phat\n", luot, loi);
}
