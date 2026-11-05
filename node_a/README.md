# Node A: lót giày LoRa (TV1)

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

Nếu biên dịch báo `undefined reference to mbedtls_cipher_cmac` thì báo TV2: core ESP32 bản đó chưa bật CMAC, sẽ đổi sang cách khác.

## Việc node phải làm đúng, nếu không gateway sẽ chặn

- [ ] Radio đúng thông số ở protocol.md mục 1 (433 MHz, SF9, BW125, CR 4/5, sync 0x12).
- [ ] Mỗi lần khởi động gửi **HELLO** (fcnt = 0, nonce = `esp_random()`), chờ ACK rồi mới gửi DATA.
- [ ] DATA đếm fcnt từ 1, tăng 1 mỗi gói **mới**. Gửi lại vì mất ACK thì giữ **nguyên gói cũ, nguyên fcnt**.
- [ ] Phát xong thì nghe ACK 600 ms. Không có thì chờ ngẫu nhiên 100–400 ms rồi gửi lại, tối đa 3 lần.
- [ ] Chỉ chấp nhận ACK có đúng node_id, đúng fcnt đang chờ, đúng MIC (`iomt_parse_ack` làm sẵn cả ba việc).
- [ ] ACK có lệnh thì làm lệnh, rồi bật `IOMT_FLAG_CMD_DONE` ở gói kế tiếp.
- [ ] Ngã thì gửi ALARM (`iomt_build_data(..., alarm = 1)`), cờ `IOMT_FLAG_FALL`.

## Thử trên máy tính

Trên Linux/WSL:

```
sudo apt install libmbedtls-dev
gcc -I. test_packet_host.c -lmbedcrypto -o t && ./t
```
