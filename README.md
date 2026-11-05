# Đồ án IoMT: lót giày, kẹp tay, giường và gateway

Môn IoT trong y tế, nhóm 4 người.

```
lót giày (ESP32 + 6 FSR + MPU6050) ──LoRa 433──┐
kẹp tay  (ESP32 + MAX30102) ───────Wi-Fi/MQTT──┼──> laptop gateway ──> ThingsBoard
giường   (STM32 + HX711, hoặc giả lập) ─RS-485─┘     (Python, SQLite)
```

## Thư mục

| Thư mục | Ai | Nội dung |
|---|---|---|
| `node_a/` | TV1 | Lót giày LoRa. Đã có sẵn `iomt_packet.h` (đóng gói + MIC, đã kiểm tra khớp từng byte với gateway) |
| `node_b/` | TV3 | Kẹp tay Wi-Fi/MQTT |
| `node_c/` | TV4 | Giường RS-485/Modbus |
| `gateway/` | TV2 | Chương trình gateway Python + firmware ESP32 cầu nối LoRa + cấu hình Mosquitto |
| `sim/` | cả nhóm | Bộ giả lập: cầu nối LoRa + 12 lót giày, kẹp tay MQTT, giường Modbus |
| `docs/` | cả nhóm | **`protocol.md` là bản thỏa thuận giữa các node và gateway**, `test_vectors.md` là các gói mẫu |

## Chạy thử toàn hệ thống trên 1 laptop, không cần phần cứng

Cần Python 3.11+ và Mosquitto. Các lệnh dưới đây viết cho cmd của Windows.

```bat
cd gateway
pip install -r requirements.txt
copy config.example.toml config.toml
```

Sửa `config.toml` để chạy với bộ giả lập:
- `[lora] port = "socket://127.0.0.1:7000"`
- `[modbus] method = "tcp"` và `port = "127.0.0.1:5020"`
- `[cloud] token = "<token gateway trên ThingsBoard>"` (để trống thì chỉ lưu SQLite)

Sau đó mở 4 cửa sổ cmd ở thư mục gốc repo:

```bat
python sim\bed_modbus_sim.py --tcp 5020
python sim\fake_lora_bridge.py -c gateway\config.toml --period 5 --fall-every 10
cd gateway && python -m iomt_gateway
python sim\wrist_mqtt_sim.py -c gateway\config.toml --period 5
```

Gateway in ra từng node chuyển sang ONLINE, các báo động, và cứ mỗi phút một dòng thống kê. Xem thêm `gateway/README.md`.

## Quy tắc chung

- Không đẩy `config.toml`, `keys.h`, `passwd` lên GitHub (`.gitignore` đã chặn sẵn).
- Đổi giao thức thì sửa `docs/protocol.md` **trước**, báo nhóm, rồi mới sửa code.
- Luôn `git pull` trước khi làm.
