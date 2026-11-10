/*
  cau_hinh.h - mọi thứ cần sửa cho từng mạch nằm ở đây, không phải sửa file .ino.
*/
#pragma once
#include <stdint.h>

// ----------------------------------------------------------------- node
#define NODE_ID 1            // phải có trong sổ đăng ký của gateway (config.toml)
#define MY_SLOT 1            // khe tdma của node này (cột slot trong config.toml)
#define FW_VERSION 3

// Khóa. 0 = dùng KHÓA THỬ bên dưới (khớp gateway/config.example.toml).
// 1 = dùng keys.h do gateway/tools/genkeys.py sinh ra (chép keys.h vào thư mục này).
#define USE_KEYS_H 0

#if !USE_KEYS_H
static const uint8_t KEY[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
static const uint8_t NET_KEY[16] = {0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
                                    0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C};
#endif

// ----------------------------------------------------------------- cách dùng kênh
// Phải giống [lora].mode trong config.toml của gateway (docs/protocol.md mục 6).
#define MODE_FREE 0          // gửi lúc nào cũng được (làm trước, để thử ACK)
#define MODE_TDMA 1          // chia khe theo beacon
#define MODE_POLL 2          // gateway hỏi lần lượt
#ifndef CHANNEL_MODE
#define CHANNEL_MODE MODE_FREE
#endif

#ifndef DEFAULT_PERIOD_S
#define DEFAULT_PERIOD_S 60
#endif
// giây giữa 2 gói DATA. Demo dùng 15. Gateway đổi được bằng lệnh SET_PERIOD.

// ----------------------------------------------------------------- chân (mạch lót giày của Tuấn Nghĩa)
// 6 FSR: VP, VN, D34, D35, D32, D33. Tất cả là ADC1 nên đọc được cả khi bật Wi-Fi.
// THỨ TỰ phải là: gót trái, má trong trái, má ngoài trái, gót phải, má trong phải, má ngoài phải.
// Chưa biết dây nào đi tới cảm biến nào: đè tay lên từng cảm biến, xem cột nào ở dòng "# F"
// đổi, rồi sắp lại mảng này cho đúng thứ tự.
static const int FSR_PINS[6] = {36, 39, 34, 35, 32, 33};

// Ra-02 (SX1278). Giống ESP32 cầu nối của gateway.
#define PIN_NSS 5
#define PIN_DIO0 26
#define PIN_RST 14
// SCK 18, MISO 19, MOSI 23 là chân SPI mặc định của ESP32, không cần khai báo.

#define PIN_LED 2            // LED có sẵn trên ESP32 DevKit
#define PIN_BUZZER -1        // chân còi, -1 = chưa gắn (lệnh còi sẽ nháy LED thay)
#define PIN_BUTTON 0         // nút BOOT: bấm = gửi ALARM (để demo báo động khi chưa có MPU6050)

// ----------------------------------------------------------------- lấy mẫu
#define SAMPLE_HZ 200        // 200 mẫu/giây mỗi kênh (chu kỳ 5 ms)

// ----------------------------------------------------------------- MPU6050 (tùy chọn)
// 1 = có gắn MPU6050 (SDA 21, SCL 22): điền peak_acc và tự gửi ALARM khi phát hiện ngã.
#ifndef HAS_MPU6050
#define HAS_MPU6050 0
#endif
#define PIN_SDA 21
#define PIN_SCL 22

// ----------------------------------------------------------------- radio
// PHẢI GIỐNG HỆT cầu nối của gateway (docs/protocol.md mục 1).
#define LORA_FREQ_MHZ 433.5
#define LORA_BW_KHZ 125.0
#define LORA_SF 7
#define LORA_CR 5            // 4/5
#define LORA_SYNC_WORD 0x12
#define LORA_POWER_DBM 14    // 25 mW. Có thể thử hạ xuống (2..14) để tiết kiệm pin sau khi đo tầm xa.
#define LORA_PREAMBLE 8

// 1 = mỗi giây in số đọc 6 cảm biến ra Serial (dòng "# F ..."), để xem và chỉnh ngưỡng.
#define DEBUG_PRINT 1
