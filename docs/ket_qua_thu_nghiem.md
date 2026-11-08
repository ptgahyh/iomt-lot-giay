# Kết quả thử nghiệm (chưa có phần cứng)

TV2 chạy ngày 05–07/11/2026 trên máy Linux, dùng các bộ giả lập trong `sim/`. Đây là số liệu **giả lập**, dùng để kiểm tra phần mềm và chọn cách dùng kênh. Báo cáo cuối vẫn phải có số đo thật (kế hoạch tuần 7).

## 1. Biên dịch firmware ESP32

Biên dịch bằng arduino-cli 1.2.2, core esp32 3.3.12, board "ESP32 Dev Module".

| Sketch | Kết quả |
|---|---|
| `gateway/bridge_firmware/lora_bridge` (RadioLib 7.8.1) | Biên dịch được, 0 cảnh báo, 311 KB (23% flash). Hàm ngắt `onPacket` nằm trong IRAM |
| `node_a/packet_selftest` + `iomt_packet.h` | Biên dịch được, 291 KB. mbedtls trong core có bật CMAC (`CONFIG_MBEDTLS_CMAC_C=y`) |

**Chưa nạp lên mạch thật.**

Bài học khi biên dịch: Arduino tự sinh prototype cho các hàm trong file .ino, và bước này sinh sai khi hàm có thuộc tính đặt ở dòng riêng (`ICACHE_RAM_ATTR` nằm trên dòng `void onPacket()`). Đã sửa bằng cách khai báo trước mọi hàm ở đầu file. Lót giày của TV1 cũng nên làm như vậy.

## 2. Phiên bản Python

45/45 test đạt trên **Python 3.11.18** (bản thấp nhất kế hoạch yêu cầu) và trên Python 3.13, với đúng các phiên bản trong `gateway/requirements.txt`. Chạy toàn hệ thống trên Python 3.11 cũng không có lỗi.

Ngày 07/11, GitHub Actions chạy lại trên **Windows** và Linux với Python 3.11 và 3.13: cả 4 tổ hợp đều đạt 45/45. Code C của lót giày cũng ra khớp từng byte với gateway.

## 3. So sánh 3 cách dùng kênh LoRa

**Điều kiện chung:**
- 12 lót giày giả lập, SF9, gói DATA 19 byte (185 ms), ACK 10 byte (144 ms).
- Mỗi node khoảng 12 s gửi 1 gói; cứ 4 gói thì 1 gói ALARM.
- Chạy 150 s cho mỗi chế độ.

**Mô hình kênh:** hai gói chồng nhau về thời gian thì hỏng cả hai. Mô hình không tính hiệu ứng capture (gói mạnh hơn hẳn vẫn lọt), nên kết quả **bi quan hơn thực tế**.

| | free (ALOHA) | poll (hỏi lần lượt) | tdma (chia khe) |
|---|---|---|---|
| Gói gateway nhận và lưu / gói node tạo | 76 / 92 (**83%**) | 133 / 135 (**98,5%**) | 123 / 123 (**100%**) |
| Gói node nhận được ACK | 59% | 98% | 100% (trừ gói đang chờ lúc dừng) |
| Lần phát bị va chạm / tổng lần phát trên kênh | 174 / 346 | 102 / 547 (gần hết là HELLO lúc khởi động) | 12 / 296 (chỉ ALARM ở khe tự do) |
| Thời gian để cả 12 node vào mạng (HELLO) | 22 s | 21 s | **6,6 s** (1 chu kỳ) |
| Trễ ACK trung vị / p95 | 439 / 518 ms | 466 / 477 ms | 436 / 513 ms |
| Bản ghi bị lưu trùng | 0 | 0 | 0 |

**Kết luận:**
- **free** không đủ cho 12 node gửi dày như vậy.
- **tdma** tốt nhất.
- **poll** là phương án lùi chấp nhận được (98,5%), đúng như kế hoạch dự kiến.

Khi chạy chế độ free với 12 node mỗi node 2 s một gói, chỉ 5% gói có ACK: kênh bị nghẽn hoàn toàn. Có thể đưa vào báo cáo làm minh họa cho lý thuyết ALOHA (`aloha_success()` trong `gateway/iomt_gateway/airtime.py`).

**Ba điều đã sửa trong giao thức nhờ thử nghiệm này** (đã ghi vào `protocol.md`):
1. **Chờ trước khi gửi lại.** Chờ ngắn 0,1–0,4 s khiến các node va chạm dây chuyền: 12 node chỉ 29% gói có ACK. Đổi thành chờ 0,5–2 s × số lần thử thì lên 69% (cùng tải, chế độ free).
2. **HELLO trong tdma** phải gửi ở khe riêng. Để 12 node tranh nhau 5 khe tự do thì mất khoảng 108 s (9 chu kỳ) mới vào đủ mạng.
3. **ALARM trong tdma**: gửi trước ở khe tự do để nhanh, mất ACK thì gửi lại ở khe riêng. Trước khi sửa có 10 gói báo động bị bỏ cuộc; sau khi sửa không còn gói nào.

Ngoài ra, thời gian chờ ACK được nâng từ 600 ms lên **800 ms**: khi có 12 node, trễ ACK p95 đo được khoảng 630 ms.

## 4. Toàn hệ thống (20 node, 3 kiểu kết nối)

Gồm 12 lót giày, 6 kẹp tay qua Mosquitto, 2 giường qua Modbus. Một Mosquitto thứ hai đóng vai ThingsBoard.

| Bài | Kết quả |
|---|---|
| 20 node chạy cùng lúc | 20/20 ONLINE |
| Tắt "ThingsBoard" 15 s | Không mất bản ghi nào; dữ liệu trong lúc mất mạng được gửi bù sau khi nối lại (tối đa 10 s) |
| Mất 20% gói mỗi chiều | Không lưu trùng (171 bản ghi = 171 cặp node/fcnt) |
| Phát lại gói cũ, gói sai khóa, node lạ (mỗi loại 10 gói) | Chặn 10/10 mỗi loại; 0 bản ghi bị lưu thêm |
| Lệnh từ web xuống lót giày, kẹp tay, giường | Cả 3 làm đúng; lót giày báo CMD_DONE |
| Mosquitto có mật khẩu + ACL | Sai mật khẩu bị từ chối; kẹp tay 21 không ghi được và không nghe trộm được topic của 22 |
| Modbus RTU qua cổng nối tiếp ảo | 8/8 lần đọc đúng, ghi lệnh trừ bì đúng |
| Gateway đọc cổng nối tiếp thật (pty), "rút USB" 10 s | Gateway tự nối lại 5 s sau khi cắm; các node quay lại ONLINE |

## 5. ThingsBoard

- **Chưa thử với ThingsBoard thật**: máy thử không ra được thingsboard.cloud, và không được phép cài ThingsBoard trên máy thử.
- Định dạng topic và JSON đã đối chiếu với [tài liệu Gateway MQTT API](https://thingsboard.io/docs/edge/reference/gateway-mqtt-api/) và khớp cả 4 loại: connect, telemetry, attributes, RPC.
- Người có tài khoản chạy `python gateway/tools/check_thingsboard.py` để kiểm tra trong 1 phút.

## 6. Chưa làm được, cần người có phần cứng hoặc máy Windows

- **Nạp firmware lên ESP32 + Ra-02 thật:** đo RSSI, khoảng cách trên 20 m, 100 gói ở 5 m nhận ≥ 99%.
- **Chạy thật trên Windows với cổng COM:** phải làm trên laptop. Phần test thì GitHub Actions đã chạy trên Windows (mục 2).
- **ThingsBoard cloud thật:** làm theo mục 5.

> **Lưu ý (nhánh chuyển SF7):** toàn bộ số liệu giả lập ở mục 3 và 4 được đo ở **SF9** (bản cũ của giao thức). Khi nhóm chốt SF7, cần chạy lại mục 3 (so sánh free / poll / tdma) và có thể rút ngắn `slot_ms`, thời gian chờ ACK.
