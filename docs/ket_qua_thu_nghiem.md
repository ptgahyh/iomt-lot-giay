# Kết quả thử nghiệm (chưa có phần cứng)

TV2 chạy ngày 05–07/11/2026 trên máy Linux, dùng các bộ giả lập trong `sim/`. Đây là số liệu **giả lập**, dùng để kiểm tra phần mềm và chọn cách dùng kênh. Báo cáo cuối vẫn phải có số đo thật (kế hoạch tuần 7).

## 1. Biên dịch firmware ESP32

Biên dịch bằng arduino-cli 1.2.2, core esp32 3.3.12, RadioLib 7.8.1, board "ESP32 Dev Module" (`esp32:esp32:esp32`). Biên dịch lại ngày 08/11 sau khi chuyển SF7 (`LORA_SF 7`, 433,5 MHz, 14 dBm):

| Sketch | Kết quả |
|---|---|
| `gateway/bridge_firmware/lora_bridge` (RadioLib 7.8.1) | Biên dịch được, 0 cảnh báo, 311 KB (23% flash), RAM 24 KB (7%). Hàm ngắt `onPacket` nằm trong IRAM |
| `node_a/packet_selftest` + `iomt_packet.h` | Biên dịch được, 291 KB (22% flash), RAM 22 KB (6%). mbedtls trong core có bật CMAC (`CONFIG_MBEDTLS_CMAC_C=y`) |

Kích thước ra đúng bằng bản SF9 (chỉ đổi hằng số). **Chưa nạp lên mạch thật.**

Bài học khi biên dịch: Arduino tự sinh prototype cho các hàm trong file .ino, và bước này sinh sai khi hàm có thuộc tính đặt ở dòng riêng (`ICACHE_RAM_ATTR` nằm trên dòng `void onPacket()`). Đã sửa bằng cách khai báo trước mọi hàm ở đầu file. Lót giày của TV1 cũng nên làm như vậy.

## 2. Phiên bản Python

45/45 test đạt trên **Python 3.11.18** (bản thấp nhất kế hoạch yêu cầu) và trên Python 3.13, với đúng các phiên bản trong `gateway/requirements.txt`. Chạy toàn hệ thống trên Python 3.11 cũng không có lỗi.

Ngày 07/11, GitHub Actions chạy lại trên **Windows** và Linux với Python 3.11 và 3.13: cả 4 tổ hợp đều đạt 45/45. Code C của lót giày cũng ra khớp từng byte với gateway.

Ngày 08/11, sau khi chuyển SF7 (commit `3915c1b`), 45/45 test vẫn đạt (chạy tay trên Python 3.13, Linux).

## 3. So sánh 3 cách dùng kênh LoRa

Đo lại ngày 08/11/2026 sau khi chuyển radio sang **SF7, 433,5 MHz, 14 dBm**. Để so sánh được, **SF9 cũng được đo lại cùng một cách** (số SF9 của bản 05–07/11 không còn dùng). Lệnh đo: `python sim/chay_do_kenh.py <free|poll|tdma> <SF> ...` (xem đầu file đó).

**Điều kiện chung:**
- 12 lót giày giả lập, gói DATA 19 byte, ACK 10 byte. Thời gian phát: SF7 là 51 ms và 41 ms, SF9 là 185 ms và 144 ms.
- Mỗi node khoảng 12 s gửi 1 gói; cứ 4 gói thì 1 gói ALARM.
- Chạy 150 s cho mỗi ca, **mỗi ca chạy 1 lần**. Có yếu tố ngẫu nhiên nên chênh vài % giữa các lần là bình thường.
- tdma: chu kỳ beacon 15 s, 5 khe tự do. Khe `slot_ms` = 350 ms cho SF7 và 600 ms cho SF9.
- poll: `period_s` = 24 (nếu để 12 thì laptop hỏi dồn dập, tải không còn so sánh được với hai chế độ kia).

**Mô hình kênh:** hai gói chồng nhau về thời gian thì hỏng cả hai. Mô hình không tính hiệu ứng capture (gói mạnh hơn hẳn vẫn lọt), nên kết quả **bi quan hơn thực tế**.

**SF7 (cấu hình hiện tại):**

| | free (ALOHA) | poll (hỏi lần lượt) | tdma (chia khe) |
|---|---|---|---|
| Gói gateway nhận và lưu / gói node tạo | 126 / 127 (**99,2%**) | 116 / 116 (**100%**) | 101 / 101 (**100%**) |
| Gói node nhận được ACK | 97,6% | 100% | 100% |
| Lần phát bị va chạm / tổng lần phát trên kênh | 49 / 333 | 16 / 392 | 7 / 244 (chỉ ALARM ở khe tự do) |
| Thời gian để cả 12 node vào mạng (HELLO) | 11,2 s | 17,6 s | **4,4 s** |
| Trễ ACK trung vị / p95 | 182 / 285 ms | 153 / 218 ms | 198 / 284 ms |
| Bản ghi bị lưu trùng | 0 | 0 | 0 |

**SF9 (đo lại để so sánh, cấu hình cũ):**

| | free (ALOHA) | poll (hỏi lần lượt) | tdma (chia khe) |
|---|---|---|---|
| Gói gateway nhận và lưu / gói node tạo | 84 / 99 (**84,8%**) | 75 / 76 (**98,7%**) | 94 / 97 (**96,9%**) |
| Gói node nhận được ACK | 71,7% | 97,4% | 96,9% |
| Lần phát bị va chạm / tổng lần phát trên kênh | 123 / 313 | 90 / 362 | 14 / 237 |
| Thời gian để cả 12 node vào mạng (HELLO) | 30,1 s | 40,3 s | 7,6 s |
| Trễ ACK trung vị / p95 | 415 / 515 ms | 466 / 477 ms | 420 / 524 ms |
| Bản ghi bị lưu trùng | 0 | 0 | 0 |

Ở tdma, hiệu số giữa "tạo" và "nhận ACK" (3 gói ở SF9, 0 ở SF7) là các gói còn đang chờ lúc dừng đo; **không có gói nào bị bỏ cuộc**.

**Kết luận:**
- Chuyển SF9 → SF7 làm gói ngắn đi 3,6 lần (51 ms thay vì 185 ms), nên kênh rảnh hơn nhiều. **free** từ 85% lên 99%: ALOHA lý thuyết cho 12 node mỗi 12 s ra 69% (SF9) và 90% (SF7) thành công ngay lần đầu, phần còn lại được gửi lại. Mọi chế độ đều tốt hơn, và trễ ACK giảm còn khoảng một nửa.
- **tdma** vẫn tốt nhất: 100%, ít va chạm nhất (7 lần), vào mạng nhanh nhất (4,4 s).
- **poll** ở SF7 cũng đạt 100%. Là phương án lùi tốt, nhưng vào mạng chậm hơn tdma.
- **free** ở SF7 đã chấp nhận được với 12 node gửi thưa (12 s một gói), nhưng vẫn có 49 va chạm. Với 20 node hoặc gửi dày hơn thì dùng tdma. Phải đo lại trên mạch thật vì mô hình kênh ở đây bi quan.

**Về `slot_ms` ở tdma.** Công thức `min_slot_ms()` cho SF7 là khoảng 243 ms, nhưng trong bộ giả lập trễ ACK p95 đo được là **khoảng 280 ms** (ngoài 51 + 41 ms phát sóng còn khoảng 100 ms để gateway xử lý và gửi ACK), nên khe phải dài hơn mức đó:

| Khe `slot_ms` (SF7) | Gói gateway lưu / tạo | Va chạm | Vào mạng đủ 12 node |
|---|---|---|---|
| 300 ms | 97 / 100 (97,0%) | 11 | 3,8 s |
| **350 ms** | 101 / 101 (100%) | 7 | 4,4 s |
| 600 ms | 98 / 100 (98,0%) | 10 | 7,4 s |

Ở khe 300 ms (sát p95) vẫn không bị bỏ cuộc gói nào nhưng va chạm nhiều hơn khe 350 ms. Ở SF9, khe 500 ms (chỉ hơn mức tối thiểu 480 ms một chút) còn tệ hơn nhiều: lưu 79 / 91 gói (86,8%), 24 gói bỏ cuộc, vì p95 của trễ ACK (506 ms) lớn hơn khe. **Quy tắc: khe phải dài hơn trễ ACK p95, không chỉ hơn công thức tối thiểu.** Đề xuất `slot_ms` = 350 cho SF7, nhưng phần 100 ms xử lý ACK là của bộ giả lập; phải đo lại trên laptop thật với cầu nối ESP32 thật qua USB. Hiện `config.example.toml` vẫn để `slot_ms = 2000` (an toàn, chưa tối ưu).

Thời gian chờ ACK 800 ms ở node vẫn còn dư nhiều (p95 chỉ khoảng 280 ms ở SF7), có thể rút xuống khoảng 500 ms sau khi đo trên mạch thật. Chưa đổi.

**Các thử nghiệm cũ dưới đây đo ở SF9 trước khi chuyển SF7.** Chúng giải thích vì sao giao thức hiện có từng cơ chế, nên giữ làm lịch sử, không dùng làm số liệu báo cáo:
- Khi chạy chế độ free với 12 node mỗi node 2 s một gói, chỉ 5% gói có ACK: kênh bị nghẽn hoàn toàn. Có thể đưa vào báo cáo làm minh họa cho lý thuyết ALOHA (`aloha_success()` trong `gateway/iomt_gateway/airtime.py`), nhưng cần chạy lại ở SF7.

**Ba điều đã sửa trong giao thức nhờ thử nghiệm ở SF9** (đã ghi vào `protocol.md`):
1. **Chờ trước khi gửi lại.** Chờ ngắn 0,1–0,4 s khiến các node va chạm dây chuyền: 12 node chỉ 29% gói có ACK. Đổi thành chờ 0,5–2 s × số lần thử thì lên 69% (cùng tải, chế độ free).
2. **HELLO trong tdma** phải gửi ở khe riêng. Để 12 node tranh nhau 5 khe tự do thì mất khoảng 108 s (9 chu kỳ) mới vào đủ mạng.
3. **ALARM trong tdma**: gửi trước ở khe tự do để nhanh, mất ACK thì gửi lại ở khe riêng. Trước khi sửa có 10 gói báo động bị bỏ cuộc; sau khi sửa không còn gói nào.

Ngoài ra, thời gian chờ ACK được nâng từ 600 ms lên **800 ms** khi còn ở SF9: khi có 12 node, trễ ACK p95 đo được khoảng 630 ms.

## 4. Toàn hệ thống (20 node, 3 kiểu kết nối)

Gồm 12 lót giày, 6 kẹp tay qua Mosquitto, 2 giường qua Modbus. Bản SF9 (05–07/11) dùng thêm một Mosquitto thứ hai đóng vai ThingsBoard.

**Chạy lại ngày 08/11 ở SF7** (chỉ những bài có dính tới kênh LoRa):
- 20 node cùng lúc: tdma (khe 350 ms, beacon 15 s), Mosquitto 2.0.18 có mật khẩu và ACL lấy từ `gateway/mosquitto/acl.conf`, giường qua Modbus TCP, chạy 100 s, tắt phần ThingsBoard.
- Ba bài còn lại chỉ chạy phần LoRa (12 lót giày, chế độ free, 100 s). Với bài tấn công, tắt mô hình va chạm (`--no-collisions`) để cả 10 gói tấn công đều tới được gateway.

| Bài | SF9 (05–07/11) | SF7 (08/11) |
|---|---|---|
| 20 node chạy cùng lúc | 20/20 ONLINE | **20/20 ONLINE**; đã lưu 63 bản ghi lót giày, 120 kẹp tay, 104 giường |
| Mất 20% gói mỗi chiều | Không lưu trùng (171 bản ghi = 171 cặp node/fcnt) | Không lưu trùng (69 bản ghi = 69 cặp node/fcnt) |
| Gói giả sai khóa (10 gói) | Chặn 10/10; 0 bản ghi bị lưu thêm | BAD_MIC 10/10; 0 bản ghi bị lưu thêm |
| Node lạ (10 gói) | Chặn 10/10; 0 bản ghi bị lưu thêm | UNKNOWN_NODE 10/10; 0 bản ghi bị lưu thêm |
| Phát lại gói cũ (10 gói) | Chặn 10/10; 0 bản ghi bị lưu thêm | REPLAY 8/10; 2 gói còn lại trùng đúng gói mới nhất nên bị coi là gửi lại (DUPLICATE, trả ACK, không lưu, xem `protocol.md` mục 5). 0 bản ghi bị lưu thêm |
| Tắt "ThingsBoard" 15 s | Không mất bản ghi nào; dữ liệu trong lúc mất mạng được gửi bù sau khi nối lại (tối đa 10 s) | chưa chạy lại |
| Lệnh từ web xuống lót giày, kẹp tay, giường | Cả 3 làm đúng; lót giày báo CMD_DONE | chưa chạy lại |
| Mosquitto: sai mật khẩu, kẹp tay 21 ghi/đọc topic của 22 | Sai mật khẩu bị từ chối; kẹp tay 21 không ghi được và không nghe trộm được topic của 22 | chưa chạy lại (chỉ kiểm tra kẹp tay đăng nhập đúng và gửi được) |
| Modbus RTU qua cổng nối tiếp ảo | 8/8 lần đọc đúng, ghi lệnh trừ bì đúng | chưa chạy lại |
| Gateway đọc cổng nối tiếp thật (pty), "rút USB" 10 s | Gateway tự nối lại 5 s sau khi cắm; các node quay lại ONLINE | chưa chạy lại |

Các bài "chưa chạy lại" không phụ thuộc SF (cloud, lệnh, ACL, Modbus, cổng nối tiếp), nên kết quả SF9 vẫn dùng được. Mỗi bài SF7 chạy 1 lần.

## 5. ThingsBoard

- **Chưa thử với ThingsBoard thật**: máy thử không ra được thingsboard.cloud, và không được phép cài ThingsBoard trên máy thử.
- Định dạng topic và JSON đã đối chiếu với [tài liệu Gateway MQTT API](https://thingsboard.io/docs/edge/reference/gateway-mqtt-api/) và khớp cả 4 loại: connect, telemetry, attributes, RPC.
- Người có tài khoản chạy `python gateway/tools/check_thingsboard.py` để kiểm tra trong 1 phút.

## 6. Chưa làm được, cần người có phần cứng hoặc máy Windows

- **Nạp firmware lên ESP32 + Ra-02 thật:** đo RSSI, khoảng cách trên 20 m, 100 gói ở 5 m nhận ≥ 99%.
- **Chạy thật trên Windows với cổng COM:** phải làm trên laptop. Phần test thì GitHub Actions đã chạy trên Windows (mục 2).
- **ThingsBoard cloud thật:** làm theo mục 5.
