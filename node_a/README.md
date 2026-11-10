# Node A: lót giày LoRa (TV1)

## Firmware đầy đủ: `lot_giay_lora/`

Đọc 6 FSR ở 200 Hz, tính dáng đi, gửi qua LoRa (free / tdma / poll), làm lệnh trong ACK. Cách nạp và danh sách việc phải làm trên mạch thật: [`lot_giay_lora/HUONG-DAN.md`](lot_giay_lora/HUONG-DAN.md).

Thử không cần mạch:

```
gcc -Wall -Wextra -I lot_giay_lora test_gait_host.c -lm -o tg && ./tg     # dáng đi, phát hiện ngã
python thu_may_tinh/chay_thu.py                                           # firmware + gateway thật
```

Đặc tả gói: `docs/protocol.md`. Gói mẫu để so: `docs/test_vectors.md`.

## Dùng `iomt_packet.h`

Chép `iomt_packet.h` và `keys.h` (TV2 gửi riêng, không có trên GitHub) vào thư mục sketch.

```cpp
#include "iomt_packet.h"
#include "keys.h"

void setup() {
  Serial.begin(115200);
  Serial.println(iomt_selftest() ? "packet OK" : "packet SAI - bao TV2");
  // ...
}
```

Core ESP32 3.x (Boards Manager > esp32 by Espressif) đã bật sẵn CMAC. Nếu dùng core cũ mà báo `undefined reference to mbedtls_cipher_cmac` thì cập nhật core lên 3.x.

## Việc node phải làm đúng, nếu không gateway sẽ chặn

- [ ] Radio đúng thông số ở protocol.md mục 1 (433,5 MHz, SF7, 14 dBm, BW125, CR 4/5, sync 0x12).
- [ ] Mỗi lần khởi động gửi **HELLO** (fcnt = 0, nonce = `esp_random()`), chờ ACK rồi mới gửi DATA.
- [ ] DATA đếm fcnt từ 1, tăng 1 mỗi gói **mới**. Gửi lại vì mất ACK thì giữ **nguyên gói cũ, nguyên fcnt**.
- [ ] Phát xong thì nghe ACK 800 ms. Không có thì chờ ngẫu nhiên 0,5–2 s × số lần đã thử rồi gửi lại, tối đa 3 lần.
- [ ] Chế độ tdma: HELLO và DATA gửi ở khe riêng (`slot` trong `keys.h`). ALARM gửi ở một khe tự do ngẫu nhiên; mất ACK thì chu kỳ sau gửi lại ở khe riêng. Xem protocol.md mục 6.
- [ ] Chỉ chấp nhận ACK có đúng node_id, đúng fcnt đang chờ, đúng MIC (`iomt_parse_ack` làm sẵn cả ba việc).
- [ ] ACK có lệnh thì làm lệnh, rồi bật `IOMT_FLAG_CMD_DONE` ở gói kế tiếp.
- [ ] Ngã thì gửi ALARM (`iomt_build_data(..., alarm = 1)`), cờ `IOMT_FLAG_FALL`.

## Thử trên ESP32

Mở `packet_selftest/packet_selftest.ino`, chép `iomt_packet.h` vào cùng thư mục, nạp lên mạch, mở Serial Monitor 115200. Phải thấy tất cả dòng OK.

Sketch này đã biên dịch được với core ESP32 3.3.12 và mbedtls có sẵn trong core (CMAC đã bật). Chưa chạy trên mạch thật.

## Thử trên máy tính

Trên Linux/WSL:

```
sudo apt install libmbedtls-dev
gcc -I. test_packet_host.c -lmbedcrypto -o t && ./t
```
