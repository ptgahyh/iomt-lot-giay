# Ghép lót giày thật vào hệ thống khi chưa có LoRa

Mạch BME3 (ESP32 + 6 FSR) cắm USB vào laptop, chạy `lot_giay_usb/lot_giay_usb.ino`. Nó đóng gói HELLO / DATA / ALARM đúng `docs/protocol.md` (có MIC, có fcnt, chờ ACK, gửi lại) và đẩy qua dây USB thay cho sóng LoRa. Gateway coi nó là **Lot giay 01**, 11 lót giày còn lại vẫn là giả lập, bảng điều khiển hiện chung.

Sau này gắn Ra-02 thì chỉ đổi chỗ in `RX ...` trong sketch thành phát LoRa, phần đóng gói và gateway giữ nguyên.

## Các bước trên Windows

1. **Tìm chân FSR** (nếu chưa làm): nạp `fsr_pin_scan`, xem `KIEM-TRA-MACH-BME3.md` bước 5. Ghi 6 chân theo thứ tự gót T, má trong T, má ngoài T, gót P, má trong P, má ngoài P.
2. **Chuẩn bị sketch**: chép `node_a\iomt_packet.h` vào `node_a\lot_giay_usb\` (cạnh file `.ino`). Mở `lot_giay_usb.ino`, sửa dòng `FSR_PINS` theo bước 1.
3. **Nạp**: Board **ESP32 Dev Module**, chọn đúng Port, Upload.
4. **Xem thử**: mở Serial Monitor 115200.
   - Phải thấy `# iomt_packet selftest OK`.
   - Mỗi giây một dòng `# F ...` (6 số đọc FSR). Ấn vào lót giày thì số tăng.
   - Cứ 5 giây một dòng `RX 03...` (HELLO, chưa có gateway nên chưa ai trả lời, vậy là đúng).
5. **ĐÓNG Serial Monitor** (đóng hẳn cửa sổ). Cổng COM chỉ một chương trình mở được, gateway cần nó.
6. **Chạy demo** ở thư mục gốc repo, thay `COM7` bằng cổng thật (Device Manager > Ports):

   ```bat
   python sim\chay_demo.py --lot-giay-that COM7
   ```

7. Trình duyệt mở http://127.0.0.1:8080. Sau khoảng 15 giây, **Lot giay 01** chuyển sang hoạt động, dòng mô tả đổi theo lực ấn (đứng, đi, % dồn lực chân trái).
8. **Thử báo động**: bấm nút **BOOT** trên ESP32, lót giày gửi ngay một gói ALARM có cờ ngã, bảng hiện báo động cho Lot giay 01.

## Lót giày tính gì từ 6 FSR

Cứ 15 giây (lệnh `set_period` đổi được) gửi một gói DATA:

| Trường | Cách tính |
|---|---|
| activity | tổng 6 kênh < 300: không có lực · có ≥ 2 bước trong chu kỳ: đi · còn lại: đứng |
| steps | mỗi lần gót trái hoặc gót phải vượt 1500 rồi xuống dưới 600 là 1 bước |
| load_left / load_right | trung bình tổng 3 kênh mỗi chân, quy về 0..255 |
| left_share | % lực chân trái |
| heel_share | % lực ở 2 gót |
| sway | độ lệch chuẩn của % lực chân trái trong chu kỳ |
| peak_acc | 0 (chưa có MPU6050) |
| battery | 100 (cấp USB) |

Ngưỡng `NO_LOAD`, `HEEL_ON`, `HEEL_OFF` ở đầu sketch. Nếu đi mà không đếm được bước, xem số gót trong dòng `# F` lúc đứng lên rồi hạ hai ngưỡng gót xuống.

## Lệnh từ gateway

`set_period` đổi chu kỳ gửi. `blink` và `buzzer_on` nháy LED GPIO2 (chưa có còi). `buzzer_off` tắt nháy. Làm xong thì gói kế tiếp có cờ CMD_DONE.

## Gặp lỗi

| Thấy | Làm |
|---|---|
| log `demo_run\cau_noi_lora.log` báo `could not open port` / `Access is denied` | Serial Monitor hoặc cửa sổ demo cũ còn mở cổng. Đóng hết rồi chạy lại |
| Lot giay 01 không lên, log không có `HELLO co ACK` | sai cổng COM, hoặc chưa nạp sketch. Bấm nút EN trên ESP32 để nó gửi HELLO lại |
| `selftest SAI` | chép nhầm `iomt_packet.h` cũ, chép lại từ repo |
| số `# F` luôn 0 hoặc luôn ~4095 | sai chân hoặc mạch hỏng, làm lại `KIEM-TRA-MACH-BME3.md` |

## Đã thử

Sketch biên dịch được trên máy tính với một lớp giả Arduino + mbedtls thật (0 cảnh báo), và chạy cùng `chay_demo.py` qua một cổng serial ảo: HELLO được ACK, DATA được lưu, nút BOOT gửi ALARM và gateway báo ngã cho node 1. **Chưa biên dịch bằng core ESP32 và chưa chạy trên mạch thật.**
