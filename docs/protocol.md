# Giao thức truyền thông: node, cầu nối LoRa, gateway

Bản **v0.1** do TV2 đề xuất ngày 05/11. TV1 và TV2 cùng duyệt. Muốn sửa bảng nào thì sửa file này, sửa `gateway/iomt_gateway/packet.py` và `node_a/iomt_packet.h`, rồi chạy lại `python tools/make_vectors.py > ../docs/test_vectors.md`. Cả ba phải luôn khớp nhau.

> Nếu "bản kế hoạch chi tiết" của nhóm đã định nghĩa gói 19 byte theo cách khác, bên nào sai thì sửa bên đó. Bản này mới đúng con số 19 byte (DATA) và 11 byte (bản tóm tắt) trong kế hoạch.

## 1. Thông số radio (giống hệt nhau trên mọi node LoRa và cầu nối)

| Thông số | Giá trị |
|---|---|
| Tần số | 433,0 MHz |
| Băng thông | 125 kHz |
| Spreading factor | 9 |
| Coding rate | 4/5 |
| Sync word | 0x12 (mạng riêng) |
| Công suất | 17 dBm |
| Preamble | 8 |
| CRC | bật |

Thời gian phát ở SF9 khoảng 185 ms cho gói 19 byte và 145 ms cho ACK 10 byte (công thức trong `gateway/iomt_gateway/airtime.py`).

- Sau khi phát xong, node nghe ACK trong **800 ms**. Trên bộ giả lập có 12 node, ACK về sau trung vị khoảng 450 ms, p95 khoảng 630 ms (tính từ lúc bắt đầu phát), nên 600 ms là quá sát.
- Không có ACK thì chờ ngẫu nhiên **0,5–2 s × số lần đã thử**, rồi gửi lại **y nguyên gói cũ** (cùng FCnt). Gửi tối đa 3 lần.
- Đừng chờ ngắn kiểu 0,1–0,4 s. Thử trên bộ giả lập: các node vừa va chạm sẽ gửi lại gần như cùng lúc và va chạm tiếp theo dây chuyền.

## 2. Khung gói

```
[type 1][node_id 1][fcnt 2][payload N][mic 4]
```

- Mọi số nhiều byte đều là **little-endian**.
- `node_id`: 1..254. Giá trị 255 là phát chung (beacon).
- `mic` = 4 byte đầu của **AES-128-CMAC(khóa, mọi byte đứng trước mic)**.
  - Khóa mỗi node khác nhau, nằm trong `config.toml` và `keys.h`.
  - Riêng beacon ký bằng `net_key`.

| type | Tên | Chiều | Độ dài | Payload |
|---|---|---|---|---|
| 0x01 | DATA | node → gw | **19** | bản tóm tắt 11 byte |
| 0x02 | ALARM | node → gw | 19 | bản tóm tắt 11 byte (có cờ FALL) |
| 0x03 | HELLO | node → gw | 13 | nonce 4 byte, phiên bản firmware 1 byte; luôn có fcnt = 0 |
| 0x81 | ACK | gw → node | 10 | lệnh 1 byte, tham số 1 byte; fcnt = fcnt của gói được xác nhận |
| 0x82 | BEACON | gw → mọi node | 12 | slot_ms 2 byte, n_slots 1 byte, free_slots 1 byte; fcnt = số thứ tự beacon |
| 0x83 | POLL | gw → node | 8 | không có; fcnt = số thứ tự lần hỏi |

## 3. Bản tóm tắt 11 byte (DATA / ALARM)

| Byte | Trường | Kiểu | Ý nghĩa |
|---|---|---|---|
| 0 | flags | u8 | bit0 FALL ngã · bit1 LOW_BATT · bit2 SENSOR_FAULT · bit3 NO_MOTION nằm yên quá lâu · bit4 CMD_DONE đã làm lệnh ở ACK trước |
| 1 | activity | u8 | 0 chưa rõ · 1 không có lực (nằm/ngồi/tháo giày) · 2 đứng · 3 đi |
| 2–3 | steps | u16 | số bước **cộng dồn** từ lúc bật (mất gói vẫn tính đúng) |
| 4 | load_left | u8 | chỉ số tải chân trái 0..255. Đây là chỉ số tương đối, **không phải kg** (FSR không đo tuyệt đối được) |
| 5 | load_right | u8 | chỉ số tải chân phải |
| 6 | left_share | u8 | % tải dồn lên chân trái (50 = cân đối) |
| 7 | heel_share | u8 | % tải ở gót |
| 8 | sway | u8 | chỉ số lắc tâm áp lực (CoP), đơn vị do TV1 định nghĩa và ghi vào đây |
| 9 | peak_acc | u8 | gia tốc lớn nhất trong cửa sổ, đơn vị 0,1 g |
| 10 | battery | u8 | % pin |

## 4. Lệnh trong ACK

| cmd | Tên | arg |
|---|---|---|
| 0 | NONE | — |
| 1 | BUZZER_OFF | — |
| 2 | BUZZER_ON | số giây (0 = kêu tới khi tắt) |
| 3 | SET_PERIOD | chu kỳ gửi, đơn vị giây |
| 4 | LED_BLINK | số lần nháy |

Node làm lệnh xong thì bật cờ **CMD_DONE** ở gói kế tiếp. Nếu sau 3 lần ACK mà gateway chưa thấy cờ này, gateway báo sự kiện CMD_FAILED.

## 5. Bảo mật (gateway kiểm tra, `security.py`)

1. `node_id` không có trong sổ đăng ký → chặn, ghi sự kiện **UNKNOWN_NODE**.
2. MIC sai → chặn, ghi **BAD_MIC**.
3. DATA/ALARM có fcnt mới hơn fcnt cuối (so kiểu quay vòng 16 bit) → nhận và trả ACK.
4. fcnt bằng fcnt cuối và nội dung y hệt → coi là node gửi lại vì mất ACK (**DUPLICATE**): trả lại đúng ACK cũ, **không lưu lần hai**.
5. Các trường hợp còn lại → chặn, ghi **REPLAY**.
6. **HELLO** dùng khi node khởi động lại: nonce mới thì gateway đặt lại fcnt = 0. HELLO cũ có nonce đã dùng thì bị chặn.
   → Node **phải gửi HELLO mỗi lần khởi động**, nonce lấy bằng `esp_random()`. Nếu không, mọi gói sau khi reset đều bị chặn vì fcnt nhỏ hơn fcnt cũ.
7. Trạng thái fcnt và nonce được lưu trong SQLite, nên khởi động lại gateway không làm mở lỗ hổng.

Gói phát lại trùng đúng gói mới nhất sẽ được xử lý như trường hợp 4 (trả ACK, không lưu). Vì vậy, khi đo bài "chặn gói cũ 10/10", hãy đếm **số bản ghi bị lưu thêm (phải bằng 0)**, đừng chỉ đếm sự kiện REPLAY.

Phần mã hóa nội dung (AES) nằm đầu danh sách được cắt trong kế hoạch, nên chưa làm. MIC chỉ chống giả mạo, **không che giấu nội dung**.

## 6. Ba chế độ dùng kênh LoRa (`[lora].mode`)

- **free** (tuần 2): node gửi lúc nào cũng được. Dùng để làm cho ACK chạy trước.
- **tdma** (tuần 5): gateway phát BEACON mỗi `beacon_period_s` giây.
  - Mốc t = 0 là lúc node *nhận xong* beacon. Khe 0 là chỗ của chính beacon. Node có `slot = k` phát trong khe k, tức từ `k·slot_ms` đến `(k+1)·slot_ms`. Nên chờ thêm khoảng 30 ms đầu khe để bù lệch đồng hồ.
  - **HELLO gửi ở khe riêng của node** (số khe có sẵn trong `keys.h`). Đã thử để HELLO tranh nhau ở khe tự do: 12 node bật cùng lúc tranh 5 khe, mất khoảng 9 chu kỳ mới vào đủ mạng. Gửi ở khe riêng thì vào đủ trong 1 chu kỳ.
  - Sau khe cuối của node là `free_slots` khe tự do, dành cho ALARM.
    - ALARM gửi ngay ở **một khe tự do chọn ngẫu nhiên**, không chờ khe của mình.
    - Không có ACK thì sang chu kỳ sau gửi lại ở **khe riêng**, chỗ chắc chắn không va chạm.
  - Chỉ bắt đầu phát nếu còn kịp phát xong và nhận ACK trước khi hết khe.
  - Gateway từ chối chạy nếu `slot_ms` ngắn hơn mức tối thiểu cho DATA + ACK ở SF đang dùng (480 ms ở SF9).
  - Mặc định: 12 node × 2 s + 1 + 5 khe = 36 s, nằm gọn trong chu kỳ 60 s.
  - Laptop có trễ vài chục ms không ảnh hưởng gì, vì mọi node đo thời gian tính từ lúc nhận beacon.
- **poll** (phương án lùi): laptop gửi POLL lần lượt cho từng node. Node trả DATA ngay, gateway trả ACK như thường.

## 7. Giao thức USB giữa laptop và ESP32 cầu nối

Dạng dòng chữ, 115200 baud. Xem `gateway/bridge_firmware/lora_bridge/lora_bridge.ino`.

```
ESP32 -> laptop:  READY lora_bridge 0.1 433.0MHz SF9 BW125
                  RX 010101000003D204786E342D110D57452F1287 -67 7.5
                  TXOK | TXERR <mã>
                  # ghi chú
laptop -> ESP32:  TX 810101000000B7C0707A          (hex liền, không dấu cách)
```

## 8. Kẹp tay qua MQTT (node B)

| Topic | Chiều | Nội dung |
|---|---|---|
| `iomt/wrist/<id>/telemetry` | kẹp tay → gw | `{"fcnt":12,"hr":78,"spo2":97,"finger":true,"batt":85}` |
| `iomt/wrist/<id>/cmd` | gw → kẹp tay | `{"seq":3,"cmd":"buzzer_on","arg":5}` |
| `iomt/wrist/<id>/ack` | kẹp tay → gw | `{"seq":3,"ok":true}` |

- Cấu hình broker: `gateway/mosquitto/`. Đã thử trên máy: sai mật khẩu bị từ chối, kẹp tay 21 không ghi được vào topic của 22 và không đọc được lệnh của 22.
- Mỗi kẹp tay đăng nhập với **username = id** (ví dụ `21`), mỗi máy một mật khẩu riêng.
- Gateway đăng nhập bằng user `gateway`.

## 9. Giường qua Modbus RTU (node C)

- RS-485, 9600 8N1. Địa chỉ Modbus là `unit_id` trong `config.toml`.
- Dùng hàm đọc holding register (FC03) và ghi một thanh ghi (FC06).

| Thanh ghi | Ý nghĩa |
|---|---|
| 0 | cân trái, đơn vị 0,1 kg |
| 1 | cân phải, đơn vị 0,1 kg |
| 2 | trạng thái: 0 trống · 1 nằm · 2 ngồi mép giường · 3 chưa rõ |
| 3 | cờ lỗi: bit0 HX711 trái · bit1 HX711 phải · bit2 chưa trừ bì |
| 4 | nhịp sống: tăng 1 sau mỗi lần đo |
| 10 | lệnh (ghi): 1 tắt còi · 2 bật còi · 3 trừ bì. Thiết bị làm xong thì tự đưa về 0 |

Giả lập tham khảo: `sim/bed_modbus_sim.py`.

## 10. ThingsBoard

- Gateway dùng Gateway MQTT API: chỉ 1 token, các thiết bị con được tạo tự động theo `name`. Định dạng topic và JSON đã đối chiếu với [tài liệu Gateway MQTT API của ThingsBoard](https://thingsboard.io/docs/edge/reference/gateway-mqtt-api/).
- Trước khi chạy gateway, chạy `python tools/check_thingsboard.py` để thử token, xem thiết bị con có được tạo không, và thử một lệnh RPC.
- Lệnh từ web gửi qua RPC, tên method là một trong `buzzer_on`, `buzzer_off`, `set_period`, `blink`, `tare`. Ví dụ params: `5` hoặc `{"arg": 5}`.
- Lệnh cho lót giày được trả lời ngay là "đã xếp hàng". Kết quả thật hiện ở telemetry `event_code` = `CMD_DONE` hoặc `CMD_FAILED`.
- Telemetry của mỗi bản ghi có thêm `risk_score`, `risk_level`, `risk_reasons`.
- Thuộc tính `status` có giá trị ONLINE, WARNING hoặc DISCONNECTED.
