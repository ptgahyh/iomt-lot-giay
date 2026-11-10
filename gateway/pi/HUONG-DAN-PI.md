# Chạy gateway trên Raspberry Pi thay cho laptop

Thầy yêu cầu gateway không phải là laptop. Cách ít rủi ro nhất là giữ nguyên toàn bộ code gateway
(Python) và chỉ đổi cái máy chạy nó: một máy tính nhúng Linux nhỏ, cắm điện là tự chạy.

**Trạng thái thật:** script `cai_dat.sh` đã chạy thử trọn vẹn trên một máy Linux họ Debian
(Ubuntu 24.04, x86): dựng môi trường Python, tạo user và ACL cho Mosquitto, gateway nhận tin của
6 kẹp tay giả có mật khẩu, kẹp tay 21 không ghi hay đọc được topic của kẹp tay 22, bảng điều khiển
mở được từ địa chỉ mạng. **Chưa chạy trên Raspberry Pi thật**, và phần systemd (tự chạy khi bật
nguồn) mới chỉ kiểm tra cú pháp file dịch vụ. Lần đầu làm trên Pi có thể phải sửa lặt vặt.

## Sơ đồ

```
lót giày ))) LoRa ))) [ESP32 cầu nối + Ra-02] --USB--\
kẹp tay  ))) Wi-Fi ))) (Mosquitto chạy ngay trên Pi)   >-- Raspberry Pi --Wi-Fi/LAN--> ThingsBoard
giường  --RS-485-- [USB-RS485] ------------------USB--/
```

ESP32 cầu nối vẫn dùng firmware `gateway/bridge_firmware/lora_bridge` như khi cắm vào laptop,
không phải viết lại gì. Nối thẳng Ra-02 vào chân SPI của Pi thì bớt được một ESP32, nhưng code
gateway hiện **chưa hỗ trợ** cách đó (phải viết thêm phần điều khiển SX1278), nên chưa dùng.

## Cần mua gì

| Món | Ghi chú |
|---|---|
| Raspberry Pi có Wi-Fi | Zero 2 W là đủ (4 nhân, 512 MB). Pi 3/4/5 cũ mượn được thì càng tốt |
| Thẻ microSD 16 GB trở lên | loại A1 |
| Nguồn 5 V 2,5 A | Zero 2 W dùng cổng micro-USB |
| Hub USB OTG (chỉ khi dùng Zero) | Zero chỉ có 1 cổng USB dữ liệu, trong khi cần 2 (ESP32 cầu nối + USB-RS485) |

Giá chưa kiểm tra, nhóm tự hỏi giá lúc mua. Orange Pi hay mini PC cũ chạy Debian/Ubuntu cũng dùng
được y như vậy, miễn có Python 3.11 trở lên.

## Các bước

1. **Ghi thẻ nhớ.** Dùng Raspberry Pi Imager, chọn *Raspberry Pi OS Lite (64-bit)* bản Bookworm trở lên.
   Trong phần cài đặt của Imager: đặt tên máy `iomt-gw`, tạo tài khoản, điền Wi-Fi, bật SSH.
2. **Vào máy.** Cắm điện, đợi 1 đến 2 phút, từ laptop cùng mạng: `ssh <tài khoản>@iomt-gw.local`.
3. **Lấy code và cài.**
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/ptgahyh/iomt-lot-giay.git
   cd iomt-lot-giay
   bash gateway/pi/cai_dat.sh
   ```
   Script hỏi một mật khẩu chung cho các kẹp tay (điền đúng số đó vào `MQTT_PASS` của firmware kẹp tay).
   Chạy lại script bao nhiêu lần cũng được, nó không ghi đè `config.toml` và mật khẩu đã có.
4. **Cắm ESP32 cầu nối và USB-RS485**, rồi xem tên cố định của chúng:
   ```bash
   ls /dev/serial/by-id/
   ```
   Dùng nguyên đường dẫn `/dev/serial/by-id/...` cho `port`. Đừng dùng `/dev/ttyUSB0`, vì số 0 hay 1
   đổi theo thứ tự cắm. Cái có chữ `CP210` thường là ESP32, cái có chữ `CH340` hay `1a86` thường là USB-RS485
   (nếu cả hai cùng loại chip thì rút một cái ra để biết cái nào).
5. **Sửa cấu hình.** `nano gateway/config.toml`: `[lora] port`, `[modbus] port`, `[cloud] token`.
   Chưa có thiết bị nào thì đặt `enabled = false` cho mục đó để log đỡ báo lỗi.
6. **Sinh khóa thật** (một lần): `cd gateway && .venv/bin/python tools/genkeys.py config.toml`, gửi `keys.h` cho TV1.
7. **Chạy.** `sudo systemctl restart iomt-gateway iomt-dashboard`. Từ giờ cứ cắm điện là hai dịch vụ tự chạy.

## Dùng hằng ngày

| Việc | Lệnh |
|---|---|
| Xem log đang chạy | `journalctl -u iomt-gateway -f` |
| Trạng thái | `systemctl status iomt-gateway` |
| Khởi động lại sau khi sửa config | `sudo systemctl restart iomt-gateway` |
| Xem bảng điều khiển | mở `http://iomt-gw.local:8080` trên máy cùng mạng |
| Cập nhật code | `git pull && sudo systemctl restart iomt-gateway iomt-dashboard` |
| Xuất số liệu cho báo cáo | `cd gateway && .venv/bin/python -m iomt_gateway --export-csv solieu.csv` |
| Thêm kẹp tay mới (id 27) | `sudo mosquitto_passwd /etc/mosquitto/iomt-passwd 27 && sudo systemctl restart mosquitto` |
| Tắt máy an toàn | `sudo poweroff`, đợi đèn xanh tắt rồi mới rút điện |

## Điều cần biết

- **Giờ hệ thống.** Pi không có pin giữ giờ. Không có mạng lúc bật thì giờ sai, kéo theo mốc thời gian
  của số liệu sai. Buổi demo phải cho Pi vào mạng trước (phát Wi-Fi từ điện thoại cũng được) và kiểm tra bằng lệnh `date`.
- **Kẹp tay nối vào đâu.** `MQTT_HOST` trong firmware kẹp tay là địa chỉ IP của Pi (`hostname -I`).
  Nên đặt IP cố định cho Pi trên bộ phát Wi-Fi, không thì mỗi lần đổi IP phải nạp lại kẹp tay.
- **Bảng điều khiển không có mật khẩu.** Ai cùng mạng cũng xem được, nên chỉ dùng trong mạng của nhóm.
  Không muốn mở ra mạng thì xóa `--host 0.0.0.0` trong `/etc/systemd/system/iomt-dashboard.service`.
- **Mất điện đột ngột** có thể hỏng thẻ nhớ. Sao lưu `config.toml` và `gateway.db` ra ngoài trước buổi bảo vệ.

## Lỗi hay gặp

| Hiện tượng | Làm gì |
|---|---|
| log báo không mở được cổng `/dev/serial/...` | sai đường dẫn, chưa cắm, hoặc vừa chạy script lần đầu mà chưa đăng nhập lại (quyền nhóm `dialout` cần đăng nhập lại, hoặc khởi động lại Pi) |
| `iomt-gateway` cứ 5 giây khởi động lại | `journalctl -u iomt-gateway -n 30` để đọc lỗi; thường là `config.toml` sai |
| kẹp tay báo `MQTT loi 5` | sai `MQTT_PASS`, hoặc id chưa có user: xem dòng "thêm kẹp tay mới" ở trên |
| kẹp tay báo `MQTT loi -2` | sai IP của Pi, hoặc Pi và kẹp tay khác mạng Wi-Fi |
| Mosquitto không chạy | `journalctl -u mosquitto -n 20`; hay gặp nhất là file mật khẩu sai quyền, chạy lại `cai_dat.sh` |
| không vào được `iomt-gw.local` | dùng địa chỉ IP (xem trong trang quản lý của bộ phát Wi-Fi) |
