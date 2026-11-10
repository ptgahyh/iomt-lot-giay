# Đo tầm xa LoRa (bài T1)

Cần: 2 ESP32 + 2 Ra-02 đã gắn ăng-ten, 1 laptop.

| Mạch | Nạp gì | Để ở đâu |
|---|---|---|
| Thu | `gateway/bridge_firmware/lora_bridge` | Cắm laptop, đặt cố định ở chỗ sẽ đặt gateway |
| Phát | `tools/do_tam_xa/phat_thu` | Chạy pin (mạch lót giày), người cầm đi tới từng điểm |

Cả hai dùng chung thông số radio với hệ thống (433,5 MHz, SF7, BW125, CR 4/5) và gói phát dài đúng 19 byte như gói DATA, nên kết quả đo áp dụng thẳng cho lót giày.

## Các bước

1. Laptop: `python tools/do_tam_xa/do_tam_xa.py ghi --port COM7` (COM của mạch thu, xem Device Manager).
2. Đứng sát mạch thu (khoảng 1 m), bấm BOOT trên mạch phát. LED sáng khoảng 30 giây trong lúc phát 100 gói, tắt là xong. Màn hình laptop phải đếm lên gần 100. Đây là lượt 1, kiểm tra mọi thứ chạy.
3. Đi tới từng điểm đo, mỗi điểm bấm BOOT 1 lần và chờ LED tắt. Ghi ra giấy: lượt mấy, cách bao nhiêu mét, qua mấy bức tường.
   Gợi ý điểm đo: 1 m, 5 m, 10 m, 25 m thẳng hành lang; rồi 10 m qua 1 tường, qua 2 tường, qua 3 tường; điểm xa nhất mà mày đi được.
4. Xong thì Ctrl+C trên laptop, rồi tính:
   ```
   python tools/do_tam_xa/do_tam_xa.py tinh so-lieu/T1_tho_20261111_1430.csv --nhan "1=1,0 2=5,0 3=10,0 4=25,0 5=10,1 6=10,2 7=10,3"
   ```
   Ra file `so-lieu/T1_<ngày>_<lần>.csv` đúng cột của báo cáo, và in bảng tỉ lệ nhận, RSSI, SNR từng điểm.

## Đọc kết quả

- **Tỉ lệ nhận** từ 95% trở lên là điểm đó đạt.
- **RSSI** so với số tính trong báo cáo: ở 25 m tính được khoảng −39 dBm khi không có vật cản. Đo thật trong nhà thường thấp hơn nhiều vì tường, người, phản xạ. Chênh lệch này là thứ đáng đưa vào báo cáo.
- **SNR** ở SF7 thu được tới khoảng −7,5 dB. Điểm có SNR tiến sát mức đó là điểm sắp mất sóng.

## Thử hạ công suất phát

Sửa `CONG_SUAT[]` trong `phat_thu.ino` thành `{14, 10, 5, 2}`. Mỗi lần bấm BOOT sẽ phát 100 gói ở từng mức, bảng kết quả tách theo cột dBm. Mức thấp nhất mà điểm xa nhất vẫn đạt 95% là mức nên dùng để tiết kiệm pin.

## Lưu ý

- File `.csv` không được đẩy lên GitHub (`.gitignore`). Chép thư mục `so-lieu/` vào thư mục chung của nhóm để làm báo cáo.
- Thử không cần mạch: `python -m pytest tools/do_tam_xa -q`.
