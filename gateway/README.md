# Gateway (TV2)

Chương trình Python chạy trên laptop:

- **Nhận dữ liệu** từ 3 kiểu kết nối:
  - LoRa qua ESP32 cầu nối cắm USB,
  - MQTT qua Mosquitto,
  - Modbus RTU qua USB-RS485.
- **Kiểm tra bảo mật**: con dấu MIC, số thứ tự FCnt, sổ đăng ký 20 node.
- **Trả ACK kèm lệnh** cho lót giày.
- **Chấm điểm nguy cơ**, lưu SQLite.
- **Đẩy lên ThingsBoard**, gửi bù khi mất mạng.
- **Nhận lệnh từ web** chuyển xuống thiết bị.

## Cài đặt (Windows)

```bat
cd gateway
pip install -r requirements.txt
copy config.example.toml config.toml
python tools\genkeys.py config.toml
```

`genkeys.py` thay các khóa thử bằng khóa ngẫu nhiên và tạo `keys.h`. Gửi `keys.h` riêng cho TV1 qua tin nhắn, **không đẩy lên GitHub**.

Sửa `config.toml`:
- `[lora] port`: cổng COM của ESP32 cầu nối, xem trong Device Manager.
- `[modbus] port`: cổng COM của USB-RS485.
- `[cloud] token`: lấy trên ThingsBoard. Vào Devices, bấm +, tạo thiết bị "Gateway", **tick "Is gateway"**, rồi copy Access token.
- `[[nodes]]`: sổ đăng ký 20 node. Mỗi node phải có `id` và `name` không trùng.

## Cài đặt trên Raspberry Pi (gateway không phải laptop)

Một lệnh `bash gateway/pi/cai_dat.sh` dựng môi trường Python, Mosquitto có mật khẩu + ACL và dịch vụ
tự chạy khi cắm điện. Xem `pi/HUONG-DAN-PI.md`. Đã thử trên máy Linux, chưa thử trên Pi thật.

## Chạy

```bat
python -m iomt_gateway
python -m iomt_gateway --export-csv solieu.csv
```

Lệnh thứ hai xuất toàn bộ số liệu ra CSV để vẽ đồ thị cho báo cáo.

## Cấu trúc code

| File | Làm gì |
|---|---|
| `iomt_gateway/packet.py` | Đóng gói / giải mã gói LoRa, tính MIC (AES-CMAC) |
| `iomt_gateway/security.py` | Chặn gói giả, gói cũ, node lạ; HELLO khi node khởi động lại |
| `iomt_gateway/lora_link.py` | Đọc/ghi ESP32 cầu nối qua USB, tự nối lại khi rút cáp |
| `iomt_gateway/lora_service.py` | ACK + lệnh đi kèm; beacon (tdma); hỏi lần lượt (poll) |
| `iomt_gateway/mqtt_local.py` | Kẹp tay qua Mosquitto |
| `iomt_gateway/modbus_poller.py` | Giường qua Modbus RTU; phát hiện thiết bị treo bằng thanh ghi nhịp sống |
| `iomt_gateway/monitor.py` | ONLINE / WARNING / DISCONNECTED |
| `iomt_gateway/risk.py` | Chấm điểm nguy cơ. **Ngưỡng tạm thời, cần nhóm duyệt** |
| `iomt_gateway/storage.py` | SQLite: số liệu, sự kiện, hàng đợi gửi bù, trạng thái FCnt |
| `iomt_gateway/thingsboard.py` | Gateway API của ThingsBoard, gửi bù, RPC |
| `iomt_gateway/app.py` | Ghép tất cả, chia luồng |
| `bridge_firmware/lora_bridge/` | Firmware ESP32 + Ra-02 làm cầu nối |
| `mosquitto/` | Cấu hình Mosquitto có mật khẩu + ACL (tuần 3) |
| `pi/` | Script cài lên Raspberry Pi, dịch vụ systemd, cấu hình Mosquitto cho Linux |
| `tools/genkeys.py` | Sinh khóa |
| `tools/make_vectors.py` | Sinh `docs/test_vectors.md` |
| `tools/check_thingsboard.py` | Thử token + thiết bị con + lệnh RPC trên ThingsBoard trong 1 phút |
| `iomt_gateway/airtime.py` | Thời gian phát LoRa, khe tối thiểu, lý thuyết ALOHA |

## Kiểm thử

```bat
pip install -r requirements-dev.txt
python -m pytest -q
```

Có 45 bài test, gồm:
- CMAC theo RFC 4493, đảo từng bit thì MIC phải sai.
- Gói cũ, gói giả, node lạ đều bị chặn; gateway khởi động lại vẫn nhớ FCnt.
- Lệnh đi kèm ACK, gửi lại, xác nhận.
- Mất mạng không mất dữ liệu.

## Đã thử những gì

Chi tiết ở `docs/ket_qua_thu_nghiem.md`. Tóm tắt:

- Firmware cầu nối biên dịch được với core esp32 3.3.12 + RadioLib 7.8.1, 0 cảnh báo.
- 45 test đạt trên Python 3.11 và 3.13, cả Windows lẫn Linux (GitHub Actions).
- Chạy được 20 node trên đủ 3 kiểu kết nối.
- Mất mạng không mất dữ liệu; mất gói không lưu trùng; chặn 10/10 gói cũ, gói giả, node lạ.
- Rút USB cầu nối thì gateway tự nối lại.
- Với 12 lót giày giả lập:

  | Chế độ | Gateway nhận được |
  |---|---|
  | tdma | 100% |
  | poll | 98,5% |
  | free | 83% |

**Chưa thử:**
- Mạch thật.
- Chạy gateway với cổng COM thật trên Windows.
- ThingsBoard cloud thật. Dùng `python tools/check_thingsboard.py` để thử nhanh.

## Lỗi hay gặp

| Hiện tượng | Làm gì |
|---|---|
| `không mở được COM5` | Sai cổng, hoặc Arduino IDE đang mở Serial Monitor cùng cổng. Đóng Serial Monitor đi |
| Lót giày bị chặn REPLAY sau khi reset | Node chưa gửi HELLO khi khởi động (protocol.md mục 5) |
| ESP32 không nối được Mosquitto | Mở port 1883 trong Windows Firewall; Mosquitto 2.x cần `listener 1883 0.0.0.0` |
| `ThingsBoard từ chối` | Sai token, hoặc thiết bị chưa tick "Is gateway" |
| Giường không trả lời | Kiểm tra A/B của RS-485 (thử đảo 2 dây), baud 9600, `unit_id` |
