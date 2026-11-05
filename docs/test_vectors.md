# Gói mẫu để kiểm tra từng byte

Sinh tự động bởi `gateway/tools/make_vectors.py`. Code C trên ESP32 phải ra đúng y hệt.

## 1. Kiểm tra AES-CMAC (RFC 4493)

Nếu hàm CMAC của bạn ra đúng 4 dòng này thì phần mã hóa đã đúng.

Khóa: `2B 7E 15 16 28 AE D2 A6 AB F7 15 88 09 CF 4F 3C`

| Dữ liệu | CMAC đầy đủ 16 byte |
|---|---|
| `(rỗng)` | `BB 1D 69 29 E9 59 37 28 7F A3 7D 12 9B 75 67 46` |
| `6B C1 BE E2 2E 40 9F 96 E9 3D 7E 11 73 93 17 2A` | `07 0A 16 B4 6B 4D 41 44 F7 9B DD 9D D0 4A 28 7C` |

Đáp án đúng theo RFC 4493: rỗng -> `BB 1D 69 29 E9 59 37 28 7F A3 7D 12 9B 75 67 46`; 16 byte -> `07 0A 16 B4 6B 4D 41 44 F7 9B DD 9D D0 4A 28 7C`.

## 2. Gói của node 1, khóa node `01 01 01 01 01 01 01 01 01 01 01 01 01 01 01 01`

| Gói | Độ dài | Hex |
|---|---|---|
| HELLO, nonce 0xA1B2C3D4, fw 1 | 13 | `03 01 00 00 D4 C3 B2 A1 01 3C 57 23 5D` |
| DATA fcnt 1 (đi bộ, 1234 bước...) | 19 | `01 01 01 00 00 03 D2 04 78 6E 34 2D 11 0D 57 45 2F 12 87` |
| ALARM fcnt 2 (cờ FALL, peak 3,5 g) | 19 | `02 01 02 00 01 03 D2 04 78 6E 34 2D 11 23 57 E5 18 F8 A8` |
| ACK cho fcnt 1, không lệnh | 10 | `81 01 01 00 00 00 B7 C0 70 7A` |
| ACK cho fcnt 2, lệnh BUZZER_ON 5 giây | 10 | `81 01 02 00 02 05 28 2F 5F B5` |
| POLL seq 7 | 8 | `83 01 07 00 4E 03 D8 45` |

## 3. Beacon, network key `2B 7E 15 16 28 AE D2 A6 AB F7 15 88 09 CF 4F 3C`

seq 3, khe 2000 ms, 12 khe node, 5 khe tự do (12 byte):

`82 FF 03 00 D0 07 0C 05 CE 7A E6 C8`

## 4. Giải nghĩa gói DATA ở mục 2

| Byte | Giá trị | Ý nghĩa |
|---|---|---|
| 0 | `01` | type = 0x01 DATA |
| 1 | `01` | node_id = 1 |
| 2..3 | `01 00` | fcnt = 1 (little-endian) |
| 4 | `00` | flags |
| 5 | `03` | activity = 3 WALKING |
| 6..7 | `D2 04` | steps = 1234 = 0x04D2 |
| 8 | `78` | load_left = 120 |
| 9 | `6E` | load_right = 110 |
| 10 | `34` | left_share = 52 % |
| 11 | `2D` | heel_share = 45 % |
| 12 | `11` | sway = 17 |
| 13 | `0D` | peak_acc = 13 -> 1,3 g |
| 14 | `57` | battery = 87 % |
| 15..18 | `45 2F 12 87` | MIC = 4 byte đầu AES-CMAC(khóa node, byte 0..14) |
