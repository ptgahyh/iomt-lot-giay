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
| `tools/genkeys.py` | Sinh khóa |
| `tools/make_vectors.py` | Sinh `docs/test_vectors.md` |

## Kiểm thử

```bat
pip install -r requirements-dev.txt
python -m pytest -q
```

Có 43 bài test, gồm:
- CMAC theo RFC 4493, đảo từng bit thì MIC phải sai.
- Gói cũ, gói giả, node lạ đều bị chặn; gateway khởi động lại vẫn nhớ FCnt.
- Lệnh đi kèm ACK, gửi lại, xác nhận.
- Mất mạng không mất dữ liệu.

## Đã thử những gì (05/11, trên Linux với bộ giả lập)

| Bài | Kết quả |
|---|---|
| 12 lót giày giả + 6 kẹp tay giả + 2 giường giả chạy cùng lúc | 20/20 node ONLINE; LoRa 231/231 gói có ACK |
| Tắt "ThingsBoard" (một Mosquitto đóng vai cloud) 15 giây | Không mất bản ghi nào, 213 bản ghi trong lúc mất mạng được gửi bù |
| Mất 20% gói mỗi chiều | Node gửi lại, gateway trả ACK lại, **không lưu trùng** (171 bản ghi = 171 cặp node/fcnt) |
| Phát lại gói cũ / gói sai khóa / node lạ, mỗi loại 10 gói | Chặn 10/10 mỗi loại |
| Lệnh từ RPC xuống lót giày, kẹp tay, giường | Cả 3 làm đúng; lót giày báo CMD_DONE |
| Ngã + giường cùng bệnh nhân | Có thêm ghi chú kiểm tra chéo ("giường vẫn báo đang nằm"...) |
| Modbus RTU qua cặp cổng nối tiếp ảo (socat) | 8/8 lần đọc đúng, ghi lệnh trừ bì đúng |
| Mosquitto có mật khẩu + ACL | Sai mật khẩu bị từ chối; giả danh kẹp tay khác bị chặn |

**Chưa thử trên phần cứng thật**:
- Firmware cầu nối mới chỉ được kiểm tra cú pháp với RadioLib 7.8.1, chưa nạp lên ESP32.
- Chưa chạy trên Windows.
- Chưa nối ThingsBoard cloud thật.
- Chế độ tdma và poll mới có unit test, chưa chạy với node thật.

## Lỗi hay gặp

| Hiện tượng | Làm gì |
|---|---|
| `không mở được COM5` | Sai cổng, hoặc Arduino IDE đang mở Serial Monitor cùng cổng. Đóng Serial Monitor đi |
| Lót giày bị chặn REPLAY sau khi reset | Node chưa gửi HELLO khi khởi động (protocol.md mục 5) |
| ESP32 không nối được Mosquitto | Mở port 1883 trong Windows Firewall; Mosquitto 2.x cần `listener 1883 0.0.0.0` |
| `ThingsBoard từ chối` | Sai token, hoặc thiết bị chưa tick "Is gateway" |
| Giường không trả lời | Kiểm tra A/B của RS-485 (thử đảo 2 dây), baud 9600, `unit_id` |
