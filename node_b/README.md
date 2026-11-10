# Node B: kẹp tay Wi-Fi/MQTT (TV3)

Topic và định dạng JSON xem `docs/protocol.md` mục 8. Tóm tắt:

- Gửi `iomt/wrist/<id>/telemetry` khoảng 5 giây một lần:
  `{"fcnt":12,"hr":78,"spo2":97,"finger":true,"batt":85}`
  - `fcnt` tăng dần; gateway chặn tin có fcnt cũ.
  - `finger` = false khi không đặt ngón tay; khi đó gateway bỏ qua phần chấm điểm.
- Nghe `iomt/wrist/<id>/cmd`, làm xong thì trả `iomt/wrist/<id>/ack` với `{"seq": <seq nhận được>, "ok": true}`.
- `<id>` phải khớp `id` trong `gateway/config.toml` (mặc định 21..26).
- Tuần 3: đăng nhập Mosquitto với username = id. Cấu hình mẫu ở `gateway/mosquitto/`.

Giả lập tham khảo cho E2: `sim/wrist_mqtt_sim.py`.

## Firmware

`kep_tay_mqtt/` là firmware ESP32 + MAX30102 theo đúng định dạng trên. Cách nạp và chỉnh:
`kep_tay_mqtt/HUONG-DAN.md`. Mới biên dịch và thử phần JSON trên máy tính, chưa chạy trên mạch thật.

Thử trên máy tính (không cần ESP32):

```
cd node_b
gcc -Wall -Wextra -Ikep_tay_mqtt test_kep_tay_host.c -o t && ./t
cd .. && python -m pytest node_b -q
```
