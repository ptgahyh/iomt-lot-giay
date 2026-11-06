# Bộ giả lập

| File | Giả lập | Dùng cho |
|---|---|---|
| `fake_lora_bridge.py` | ESP32 cầu nối + 12 lót giày (HELLO, DATA, ALARM, gửi lại, làm lệnh) ở cả 3 chế độ free/tdma/poll. Có thời gian phát thật, va chạm sóng (`--no-collisions` để tắt), mất gói `--loss`, tấn công `--attack replay/forge/unknown`, `-v` để in từng va chạm | TV2 thử gateway khi chưa có Ra-02. Gateway nối qua `socket://127.0.0.1:7000` |
| `wrist_mqtt_sim.py` | kẹp tay MQTT | tham khảo cho E2 (TV3) |
| `bed_modbus_sim.py` | giường Modbus TCP hoặc RTU | tham khảo cho E3 (TV4) |

Bộ E1/E1b của TV1 chạy trên ESP32 thật và phát LoRa thật. `fake_lora_bridge.py` thì khác: nó giả lập luôn cả cầu nối, nên không cần mạch nào.
