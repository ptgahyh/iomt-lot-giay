# Lót giày qua LoRa: nạp và chạy

Sketch `lot_giay_lora.ino` là firmware đầy đủ của node A: đọc 6 cảm biến lực 200 lần/giây, tự tính dáng đi, gửi gói 19 byte qua LoRa theo đúng `docs/protocol.md`.

**Trạng thái:** đã biên dịch được cho ESP32 (core esp32 3.3.12 + RadioLib 7.8.1, không cảnh báo) và đã chạy thử trên máy tính với gateway thật của nhóm ở cả 3 chế độ kênh. **Chưa chạy trên mạch thật.**

| Cấu hình | Flash | RAM tĩnh |
|---|---|---|
| free, không MPU6050 | 342.834 byte (26%) | 23.668 byte (7%) |
| tdma + MPU6050 | 366.650 byte (27%) | 25.068 byte (7%) |

## Nối dây

| Ra-02 | ESP32 |
|---|---|
| 3.3V | 3V3 (**không cắm 5 V**) |
| GND | GND |
| NSS | D5 |
| SCK | D18 |
| MISO | D19 |
| MOSI | D23 |
| RST | D14 |
| DIO0 | D26 |

6 cảm biến lực: VP (36), VN (39), D34, D35, D32, D33. MPU6050 (nếu có): SDA D21, SCL D22, VCC 3V3.

**Gắn ăng-ten trước khi cấp điện.**

## Nạp

1. Arduino IDE: cài gói **esp32 by Espressif** bản 3.x và thư viện **RadioLib bản 7.8.1**.
2. Chép `node_a/iomt_packet.h` vào thư mục `lot_giay_lora/` (cạnh file `.ino`).
3. Mở `lot_giay_lora.ino`, chọn board **ESP32 Dev Module**, Upload.
4. Mở Serial Monitor 115200. Phải thấy lần lượt:
   ```
   # lot giay LoRa, node 1, fw 3, khe 1, che do free, chu ky 60 s, 200 mau/giay
   # iomt_packet selftest OK
   # radio OK
   # F 12 30 8 | 15 22 9  buoc 0  mau 200
   ```
   - `# LOI begin ma -2`: ESP32 không thấy Ra-02. Kiểm tra dây NSS, SCK, MISO, MOSI, RST và nguồn 3,3 V.
   - Dòng `# F` in 6 số đọc mỗi giây. Đè tay lên từng cảm biến xem cột nào đổi.

## Việc phải làm trên mạch thật

1. **Xếp đúng thứ tự cảm biến.** `FSR_PINS` trong `cau_hinh.h` phải theo thứ tự: gót trái, má trong trái, má ngoài trái, gót phải, má trong phải, má ngoài phải. Đè từng cảm biến, ghi lại cột nào đổi, rồi sắp lại mảng.
2. **Chỉnh ngưỡng.** `GAIT_NO_LOAD`, `GAIT_HEEL_ON`, `GAIT_HEEL_OFF` trong `gait.h` là số đoán. Xem số ở dòng `# F` lúc đứng và lúc nhấc chân rồi đặt lại. Số bước đếm sai thì gần như chắc chắn do ngưỡng gót.
3. **Kiểm tra nhịp lấy mẫu.** Dòng `# DATA ... 12000 mau` với chu kỳ 60 s nghĩa là đúng 200 mẫu/giây.

## Chạy cùng gateway

- ESP32 thứ hai nạp `gateway/bridge_firmware/lora_bridge`, cắm vào máy chạy gateway.
- `CHANNEL_MODE` trong `cau_hinh.h` phải giống `[lora].mode` trong `config.toml`. Bắt đầu bằng `MODE_FREE`.
- `NODE_ID`, `MY_SLOT` và khóa phải khớp sổ đăng ký của gateway. Khóa thử có sẵn khớp `config.example.toml`. Dùng khóa thật thì đặt `USE_KEYS_H 1` và chép `keys.h` vào thư mục này.
- Khi chạy đúng: Serial Monitor in `# HELLO co ACK, da vao mang`, sau đó mỗi chu kỳ in `# DATA fcnt N ...` rồi `# ACK fcnt N, rssi ..., snr ...`.
- Bấm nút BOOT trên ESP32 để gửi một gói ALARM (thử báo động khi chưa có MPU6050).

## MPU6050

Đặt `HAS_MPU6050 1` trong `cau_hinh.h`. Firmware sẽ điền `peak_acc` và tự gửi ALARM khi thấy va đập trên 2,5 g rồi nằm yên 1,5 s (`fall.h`). Ngưỡng này chưa đo trên người thật.

## Chưa làm

- Đo pin: trường `battery` luôn là 100 vì mạch chưa có cầu chia áp đưa điện áp pin vào ADC.
- Ngủ tiết kiệm điện giữa các lần phát.
- Cờ `NO_MOTION`.
