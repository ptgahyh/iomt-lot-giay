# Firmware kẹp tay (node B): ESP32 + MAX30102 qua Wi-Fi/MQTT

Trạng thái thật: đã biên dịch được cho ESP32 (928 kB flash, khoảng 50 kB RAM tĩnh), phần tạo và
đọc JSON đã thử trên máy tính với gateway thật (`node_b/test_kep_tay_host.c`,
`node_b/test_kep_tay_gateway.py`). **Chưa chạy trên mạch thật lần nào.** Ngưỡng `FINGER_IR_MIN`
và độ ổn định của số nhịp tim, SpO2 phải chỉnh và đo khi có MAX30102 trong tay.

Số nhịp tim và SpO2 của MAX30102 chỉ để trình diễn hệ thống, không phải thiết bị y tế.

## Cần gì

- ESP32 DevKit và mô đun MAX30102.
- Arduino IDE có gói ESP32, cài thêm 2 thư viện trong Library Manager:
  **PubSubClient** (Nick O'Leary, 2.8) và **SparkFun MAX3010x Pulse and Proximity Sensor Library** (1.1.2).
- Gateway đang chạy Mosquitto, cùng mạng Wi-Fi 2.4 GHz với ESP32 (ESP32 không bắt được 5 GHz).

## Đấu dây

| MAX30102 | ESP32 |
|---|---|
| VIN | 3V3 |
| GND | GND |
| SDA | D21 |
| SCL | D22 |

Chân INT của MAX30102 không cần nối.

## Các bước

1. Chép `cau_hinh.h` thành `cau_hinh_rieng.h` (file này không bị đẩy lên GitHub), sửa
   `WIFI_SSID`, `WIFI_PASS`, `MQTT_HOST` (địa chỉ IP của gateway), `NODE_ID` (21..26, mỗi mạch một số),
   `MQTT_PASS` (mật khẩu của user trùng tên với id trong Mosquitto, để `""` nếu broker chưa bật mật khẩu).
2. Nạp `kep_tay_mqtt.ino`, mở Serial Monitor 115200. Thứ tự dòng mong đợi:
   `# MAX30102 OK`, `# Wi-Fi OK, IP ...`, `# MQTT OK`, rồi 5 giây một dòng `# gui {...}`.
3. Chỉnh ngưỡng ngón tay: xem dòng `# ir trung binh ...` lúc không đặt tay và lúc đặt tay,
   chọn `FINGER_IR_MIN` nằm giữa hai số đó.
4. Trên gateway xem tin đến: `mosquitto_sub -h 127.0.0.1 -u gateway -P <mật khẩu> -t "iomt/wrist/#" -v`.
5. Thử lệnh xuống: `mosquitto_pub -h 127.0.0.1 -u gateway -P <mật khẩu> -t iomt/wrist/21/cmd -m "{\"seq\": 1, \"cmd\": \"blink\", \"arg\": 3}"`,
   LED nháy 3 lần và có tin `iomt/wrist/21/ack` với `{"seq":1,"ok":true}`.

## Lỗi hay gặp

| Dòng Serial | Nghĩa | Sửa |
|---|---|---|
| `# MAX30102 KHONG THAY` | không thấy cảm biến trên I2C | xem lại SDA/SCL, nguồn 3V3 |
| không có `# Wi-Fi OK` | sai tên, mật khẩu hoặc mạng 5 GHz | dùng mạng 2.4 GHz, thử phát Wi-Fi từ điện thoại |
| `# MQTT loi -2` | không tới được broker | sai `MQTT_HOST`, tường lửa chặn cổng 1883, khác mạng |
| `# MQTT loi 5` hoặc `4` | broker từ chối đăng nhập | user = id chưa tạo trong `passwd`, hoặc sai `MQTT_PASS` |
| `finger` luôn `false` | ngưỡng quá cao | làm bước 3 |

## Hoạt động thế nào

- Lấy 25 mẫu/giây (cảm biến lấy 100 mẫu/giây rồi tự trung bình 4), giữ 100 mẫu gần nhất (4 giây).
- Mỗi chu kỳ (mặc định 5 s) chạy thuật toán của hãng Maxim có trong thư viện SparkFun để ra nhịp tim và SpO2.
  Số ngoài khoảng hợp lý (nhịp 30..220, SpO2 70..100) hoặc lúc không có ngón tay thì **bỏ trường đó**
  khỏi JSON chứ không gửi số 0, để gateway không chấm điểm nguy cơ trên số rác.
- `fcnt` bắt đầu từ 1 mỗi lần bật nguồn; gateway coi fcnt ≤ 3 là mạch vừa khởi động lại.
- Mất Wi-Fi hoặc mất broker thì tự nối lại, không treo. Tin trong lúc mất kết nối bị bỏ (không lưu bù).
- Lệnh: `buzzer_on` (arg = số giây), `buzzer_off`, `set_period` (arg = giây, 1..3600), `blink` (arg = số lần).
  Chưa gắn còi (`PIN_BUZZER -1`) thì lệnh còi bật LED thay.
