/*
  cau_hinh.h - sửa file này cho từng mạch và từng mạng Wi-Fi. KHÔNG đẩy mật khẩu thật lên GitHub:
  chép file này thành cau_hinh_rieng.h (đã có trong .gitignore) rồi sửa ở đó cũng được.
*/
#pragma once

#define WIFI_SSID "ten-wifi"
#define WIFI_PASS "mat-khau-wifi"

#define MQTT_HOST "192.168.1.10"   // địa chỉ IP của gateway (máy chạy Mosquitto)
#define MQTT_PORT 1883
#define NODE_ID 21                 // phải có trong config.toml của gateway (kind = "wrist")
#define MQTT_PASS "pw123"          // mật khẩu của user "21" trong Mosquitto; "" nếu broker chưa bật mật khẩu
#define TOPIC_PREFIX "iomt/wrist"

#ifndef DEFAULT_PERIOD_S
#define DEFAULT_PERIOD_S 5         // giây giữa 2 bản tin; gateway đổi được bằng lệnh set_period
#endif

// MAX30102 nối I2C: SDA 21, SCL 22, VIN 3V3, GND
#define PIN_SDA 21
#define PIN_SCL 22
#define PIN_LED 2                  // LED có sẵn trên ESP32 DevKit
#define PIN_BUZZER -1              // chân còi, -1 = chưa gắn (lệnh còi sẽ bật LED thay)

// Tín hiệu hồng ngoại trung bình dưới mức này = không có ngón tay trên cảm biến.
// Số khởi đầu, chỉnh lại theo số in ở dòng "# ir ..." khi có và không có ngón tay.
#define FINGER_IR_MIN 50000
