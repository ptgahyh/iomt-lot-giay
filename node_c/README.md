# Node C: giường cân bằng RS-485/Modbus (TV4)

Bảng thanh ghi xem `docs/protocol.md` mục 9. Giả lập E3 dùng ngay được:

```bat
python sim\bed_modbus_sim.py --serial COM7 --baud 9600
python sim\bed_modbus_sim.py --tcp 5020
```

Lệnh đầu chạy trên laptop thứ hai có USB-RS485. Lệnh sau dùng để thử trên 1 máy.

Khi làm giường thật trên STM32:
- Giữ đúng địa chỉ thanh ghi 0–4 và 10.
- 9600 8N1.
- Tăng thanh ghi 4 (nhịp sống) sau mỗi lần đo, để gateway biết thiết bị còn chạy.
