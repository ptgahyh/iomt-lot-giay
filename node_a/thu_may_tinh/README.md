# Thử firmware lót giày trên máy tính

`chay_thu.py` biên dịch `lot_giay_lora.ino` thành chương trình chạy trên máy tính (Arduino và RadioLib được thay bằng bản giả trong `mock/`), rồi cho nó nói chuyện với **gateway thật** của nhóm qua một cổng TCP đóng vai ESP32 cầu nối.

```
sudo apt install g++ libmbedtls-dev
pip install -r gateway/requirements.txt
python node_a/thu_may_tinh/chay_thu.py          # free, tdma, poll; khoảng 2 phút
```

Kiểm tra được: HELLO, ACK, gửi lại, fcnt, MIC, khe tdma, POLL, báo động, nhịp 200 mẫu/giây.

Không kiểm tra được: sóng thật, dây nối, ADC thật, độ trôi đồng hồ của ESP32. Những thứ đó phải thử trên mạch.

Bài thử này đã bắt được 2 lỗi trước khi có mạch: ở tdma node có khe nằm giữa chu kỳ chỉ gửi mỗi 2 beacon một lần, và ở poll một gói DATA còn nợ bị gửi sau gói ALARM nên bị gateway chặn vì REPLAY.
