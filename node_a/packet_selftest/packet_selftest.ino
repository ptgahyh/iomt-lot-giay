/*
  Tự kiểm tra iomt_packet.h trên ESP32 (TV1 chạy 1 lần khi mới lấy code về).

  Cách dùng: chép node_a/iomt_packet.h vào thư mục này (cạnh file .ino), mở bằng
  Arduino IDE, chọn board "ESP32 Dev Module", Upload, mở Serial Monitor 115200.
  Phải thấy tất cả dòng OK. Có dòng SAI thì báo TV2.

  Đã biên dịch được với core esp32 3.3.12 + RadioLib 7.8.1 (chưa chạy trên mạch thật).
*/
#include "iomt_packet.h"

void show(const char* name, bool ok);
void setup();
void loop();

void show(const char* name, bool ok) {
  Serial.print(name);
  Serial.println(ok ? " ... OK" : " ... SAI");
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("== iomt_packet selftest ==");

  uint8_t k[16];
  memset(k, 0x01, 16);
  uint8_t out[32];

  show("DATA fcnt 1 khop test_vectors", iomt_selftest());

  iomt_summary_t s = {IOMT_FLAG_FALL, IOMT_ACT_WALKING, 1234, 120, 110, 52, 45, 17, 35, 87};
  iomt_build_data(out, k, 1, 2, &s, 1);
  static const uint8_t alarm[19] = {0x02, 0x01, 0x02, 0x00, 0x01, 0x03, 0xD2, 0x04, 0x78, 0x6E,
                                    0x34, 0x2D, 0x11, 0x23, 0x57, 0xE5, 0x18, 0xF8, 0xA8};
  show("ALARM fcnt 2", memcmp(out, alarm, 19) == 0);

  iomt_build_hello(out, k, 1, 0xA1B2C3D4, 1);
  static const uint8_t hello[13] = {0x03, 0x01, 0x00, 0x00, 0xD4, 0xC3, 0xB2, 0xA1, 0x01,
                                    0x3C, 0x57, 0x23, 0x5D};
  show("HELLO", memcmp(out, hello, 13) == 0);

  static const uint8_t ack[10] = {0x81, 0x01, 0x02, 0x00, 0x02, 0x05, 0x28, 0x2F, 0x5F, 0xB5};
  iomt_ack_t a;
  show("ACK BUZZER_ON 5", iomt_parse_ack(ack, 10, k, 1, 2, &a) && a.cmd == IOMT_CMD_BUZZER_ON && a.arg == 5);
  show("ACK sai fcnt bi bo", !iomt_parse_ack(ack, 10, k, 1, 3, &a));

  // đo thời gian tính 1 gói (để biết có ảnh hưởng thời gian chờ ACK không)
  uint32_t t0 = micros();
  for (int i = 0; i < 100; i++) iomt_build_data(out, k, 1, i, &s, 0);
  Serial.print("thoi gian dong goi + MIC: ");
  Serial.print((micros() - t0) / 100.0, 1);
  Serial.println(" us/goi");
  Serial.println("== xong ==");
}

void loop() {}
