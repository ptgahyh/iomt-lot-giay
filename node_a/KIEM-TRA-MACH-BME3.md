# Kiểm tra lại mạch lót giày BME3

Làm từ trên xuống, xong bước nào tick bước đó. Hết khoảng 1 tiếng.

## Code cũ cho biết gì

File `bmedes3.html` là **trang web**, không phải code ESP32. Nó cho biết:

- 1 ESP32 gửi **6 số** một dòng, dạng `a,b,c,d,e,f\n`, qua BLE (UUID service `4fafc201-…`, characteristic `beb5483e-…`, đúng mẫu ví dụ BLE_server của ESP32).
- Thứ tự 6 số: **gót trái, má trong trái (đốt bàn 1), má ngoài trái (đốt bàn 5), gót phải, má trong phải, má ngoài phải**. Tức 3 FSR mỗi chân, 1 mạch cho cả 2 chân.
- Thang số là **0..1023**, nên code ESP32 cũ hoặc đặt `analogReadResolution(10)` hoặc chia 4 từ 0..4095.

Nó **không** cho biết: FSR nối chân GPIO nào, điện trở chia áp bao nhiêu. Hai cái này phải dò trên mạch (bước 3 và 5).

## Cần chuẩn bị

- Đồng hồ vạn năng (thang Ω, thang V DC, thang kêu tít)
- Cáp USB, máy có Arduino IDE + core ESP32
- Sketch `fsr_pin_scan/fsr_pin_scan.ino` (trong thư mục này) và `01_fsr_test`
- Bảng ghi ở cuối file

## Bước 1. Nhìn bằng mắt (chưa cắm điện)

- [ ] Mối hàn ở chân ESP32, đầu dây FSR, điện trở: có mối nào nứt, xám, dính sang chân bên cạnh không.
- [ ] **Đuôi FSR402** (đoạn dẹt có 2 chân bạc): đây là chỗ hay gãy nhất. Xem có bị gập gãy, chảy nhựa do hàn quá nóng, hay bong lớp bạc không.
- [ ] Mặt tròn FSR có bị rách, phồng, dính keo lệch không.
- [ ] Dây từ lót giày về mạch có bị đứt ngầm ở chỗ gập (cổ chân, mép giày) không. Kéo nhẹ từng sợi.
- [ ] Ghi lại: mạch có pin không, có công tắc không, mạch cấp nguồn bằng USB hay pin.

## Bước 2. Đo ngắn mạch nguồn (chưa cắm điện)

Thang Ω hoặc thang kêu tít.

- [ ] Đo giữa **3V3 và GND**: phải **không kêu**, số đo từ vài kΩ trở lên. Nếu kêu tít hoặc < 10 Ω là chập, **đừng cắm điện**, tìm chỗ chập trước.
- [ ] Đo giữa **5V/VIN và GND**: tương tự.
- [ ] Đo thông mạch GND: chân GND của ESP32 tới đầu GND của từng điện trở chia áp phải kêu tít.

## Bước 3. Dò cách mắc từng FSR (chưa cắm điện)

FSR402 thường mắc kiểu chia áp như sau (gọi là **kéo xuống**):

```
3V3 ── FSR ──┬── GPIO (ADC)
             │
             R (thường 10 kΩ)
             │
            GND
```

Không ấn thì FSR gần như hở (> 1 MΩ), GPIO ≈ 0 V. Ấn mạnh thì FSR còn vài trăm Ω tới vài kΩ, GPIO lên gần 3 V.

Với từng FSR:

- [ ] Lần theo dây: một đầu FSR về **3V3**, đầu kia về **một chân GPIO** và **một điện trở**. Dùng thang kêu tít để chắc chắn. Ghi chân GPIO vào bảng.
- [ ] Đọc giá trị điện trở: vòng màu **nâu đen cam = 10 kΩ**, SMD ghi **103 = 10 kΩ**, **472 = 4,7 kΩ**. Hoặc đo trực tiếp (đo trên mạch có thể ra hơi thấp hơn, chênh ít thì được).
- [ ] Đo điện trở 2 chân FSR: không ấn phải ra rất lớn hoặc OL; ấn ngón cái mạnh phải tụt xuống vài kΩ hoặc thấp hơn. Đo trên mạch thì con số có thể bị điện trở khác mắc song song làm thấp đi, **quan trọng là ấn vào thì số phải giảm mạnh**. Không đổi gì khi ấn là FSR hỏng hoặc đứt dây.
- [ ] Nếu thấy mắc **ngược** (FSR về GND, điện trở về 3V3): vẫn dùng được, nhưng giá trị sẽ **giảm** khi ấn. Ghi lại để sửa code.

### Kiểm tra chân có hợp với node A mới không

Node A mới dùng LoRa Ra-02 nối các chân **5, 14, 18, 19, 23, 26, 27** (và I2C **21, 22** nếu sau này gắn MPU6050). So với chân FSR vừa ghi:

- [ ] FSR **không** được trùng các chân trên. Trùng thì phải chuyển dây FSR sang chân khác hoặc đổi chân LoRa.
- [ ] Tốt nhất 6 FSR nằm ở **6 chân ADC1: 36, 39, 34, 35, 32, 33**. Chân ADC2 (25, 26, 27, 14, 12, 13, 15, 2, 4, 0) vẫn đọc được nếu node không bật Wi-Fi, nhưng sẽ không dùng được nếu sau này bật Wi-Fi.
- [ ] Nếu có FSR ở **GPIO12**: cẩn thận, chân này mà bị kéo lên lúc khởi động thì ESP32 có thể không boot được. Kiểu mắc kéo xuống như trên thì không sao.
- [ ] Nếu có FSR ở **GPIO0, 2, 15**: đây là chân khởi động, nên chuyển sang chân khác.

## Bước 4. Cắm điện, đo áp

Cắm USB vào ESP32 (chưa cần nạp code).

- [ ] Chân **3V3** so với GND: **3,2 đến 3,35 V**.
- [ ] Chân **5V/VIN** (khi cắm USB): **4,7 đến 5,1 V**.
- [ ] Nếu chạy pin: đo áp pin, ghi lại.
- [ ] Sờ ESP32 và mạch nguồn sau 1 phút: không được nóng tay.
- [ ] Ở mỗi chân GPIO của FSR, so với GND:
  - không ấn: **0 đến 0,1 V**
  - ấn ngón cái mạnh: **1,5 đến 3 V**

Đọc kết quả:

| Đo được | Nghĩa là |
|---|---|
| không ấn ≈ 0 V, ấn lên 1,5–3 V | tốt |
| luôn ≈ 0 V dù ấn | FSR đứt, dây 3V3 tới FSR đứt, hoặc đuôi FSR gãy |
| luôn ≈ 3,3 V | FSR bị chập, hoặc điện trở xuống GND bị đứt/thiếu |
| nhảy lung tung, chạm tay vào cũng đổi | chân đang thả nổi: điện trở hoặc dây GND bị đứt |
| ấn chỉ lên 0,2–0,5 V | điện trở chia áp quá nhỏ, hoặc FSR đã yếu. Thử điện trở 10–47 kΩ |

## Bước 5. Dò chân bằng code

Dùng khi không lần được dây hoặc muốn chắc chắn.

- [ ] Mở `fsr_pin_scan/fsr_pin_scan.ino`, Board **ESP32 Dev Module**, nạp lên.
- [ ] Mở Serial Monitor **115200**, chọn **Newline**.
- [ ] Vừa nạp xong thì **để yên lót giày 3 giây**. Nó in bảng giá trị nền của mọi chân.
  - Chân FSR tốt: nền **dưới 100**.
  - Chân không nối gì: số linh tinh, thường vài trăm hoặc hơn.
- [ ] Ấn lần lượt: gót T, má trong T, má ngoài T, gót P, má trong P, má ngoài P. Mỗi lần ấn sẽ hiện `>>> GPIOxx DANG BI AN`. Ghi chân vào bảng.
- [ ] Ấn 1 FSR mà hiện **2 chân** thì 2 dây đang chạm nhau, hoặc chập ở đâu đó.
- [ ] Ấn mà **không chân nào hiện** thì quay lại bước 4 đo áp ở FSR đó.
- [ ] Gõ `t` + Enter khi đang ấn để xem số của mọi chân; gõ `b` + Enter để đo lại nền.

## Bước 6. Chạy bài 1 với chân đúng

- [ ] Mở `01_fsr_test`, sửa dòng `FSR_PINS` theo bảng, **đúng thứ tự** gót T, má trong T, má ngoài T, gót P, má trong P, má ngoài P (giữ thứ tự giống BME3 cho dễ so).
- [ ] Nạp, mở **Serial Plotter** 115200. Phải thấy 6 đường, ấn chỗ nào thì đúng đường đó lên.
- [ ] Dòng `# toc_do=` phải ≈ **1000 Hz**, `tre=0`.
- [ ] Đứng lên lót giày (2 chân), dồn trọng tâm ra gót rồi ra mũi: đường gót và đường má phải đổi chỗ cho nhau.

### Đạt khi

- Không ấn: cả 6 kênh **< 100** (thang 0..4095).
- Ấn ngón cái mạnh: **> 2000**.
- Đứng cả người lên: kênh gót **> 3000**.
- Ấn 1 kênh thì 5 kênh còn lại đổi **< 50**.
- Ấn rồi nhả 10 lần, lần nào cũng về lại **< 100**.

## Bảng ghi

Điền xong chụp gửi vào nhóm.

| Kênh | Vị trí | GPIO | R chia áp | V không ấn | V ấn mạnh | ADC không ấn | ADC ấn mạnh | Ghi chú |
|---|---|---|---|---|---|---|---|---|
| F1 | Gót trái | | | | | | | |
| F2 | Má trong trái | | | | | | | |
| F3 | Má ngoài trái | | | | | | | |
| F4 | Gót phải | | | | | | | |
| F5 | Má trong phải | | | | | | | |
| F6 | Má ngoài phải | | | | | | | |

Ngoài ra ghi: áp 3V3 = ___ V, áp 5V = ___ V, có pin không ___, các chân GPIO còn trống ___.
