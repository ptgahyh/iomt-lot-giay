/*
  fall.h - phát hiện ngã từ gia tốc kế (MPU6050), C thuần. CHỈ DÙNG KHI CÓ MPU6050.

  Luật đơn giản, 2 pha:
    1. Va đập: độ lớn gia tốc vượt FALL_IMPACT_MG.
    2. Nằm yên: trong FALL_WINDOW_MS sau va đập, có FALL_STILL_MS liên tục mà độ lớn
       gia tốc nằm quanh 1 g (không còn chuyển động).
  Đi, chạy, giậm chân có va đập nhưng không có pha nằm yên ngay sau đó, nên không báo.
  Ngưỡng là giá trị khởi đầu, CHƯA ĐO TRÊN NGƯỜI THẬT; phải chỉnh bằng dữ liệu thật.

  Cách dùng: gọi fall_feed() đều FALL_FS lần mỗi giây, trả 1 đúng một lần khi phát hiện ngã.
*/
#ifndef IOMT_FALL_H
#define IOMT_FALL_H

#include <stdint.h>
#include <string.h>

#ifndef FALL_FS
#define FALL_FS 50
#endif
#ifndef FALL_IMPACT_MG
#define FALL_IMPACT_MG 2500   /* 2,5 g */
#endif
#define FALL_WINDOW_MS 5000
#define FALL_STILL_MS 1500
#define FALL_STILL_LOW_MG 800
#define FALL_STILL_HIGH_MG 1200

typedef struct {
  uint32_t window_left;   /* số mẫu còn lại của cửa sổ sau va đập, 0 = chưa có va đập */
  uint32_t still;         /* số mẫu nằm yên liên tục */
  uint32_t peak_mg;       /* gia tốc lớn nhất từ lần lấy gần nhất */
} fall_t;

static inline void fall_init(fall_t* f) { memset(f, 0, sizeof(*f)); }

/* Căn bậc hai số nguyên, đủ dùng cho độ lớn gia tốc (không cần math.h). */
static inline uint32_t fall_isqrt(uint64_t x) {
  uint64_t r = 0, bit = (uint64_t)1 << 62;
  while (bit > x) bit >>= 2;
  while (bit) {
    if (x >= r + bit) { x -= r + bit; r = (r >> 1) + bit; }
    else r >>= 1;
    bit >>= 2;
  }
  return (uint32_t)r;
}

/* ax, ay, az tính bằng mg (1000 = 1 g). Trả 1 khi vừa phát hiện ngã. */
static inline int fall_feed(fall_t* f, int32_t ax, int32_t ay, int32_t az) {
  uint32_t mag = fall_isqrt((uint64_t)((int64_t)ax * ax + (int64_t)ay * ay + (int64_t)az * az));
  if (mag > f->peak_mg) f->peak_mg = mag;

  if (mag > FALL_IMPACT_MG) {                       /* va đập (mới hoặc lặp lại): mở lại cửa sổ */
    f->window_left = (uint32_t)FALL_FS * (FALL_WINDOW_MS + FALL_STILL_MS) / 1000;
    f->still = 0;
    return 0;
  }
  if (f->window_left == 0) return 0;
  f->window_left--;
  if (mag >= FALL_STILL_LOW_MG && mag <= FALL_STILL_HIGH_MG) f->still++;
  else f->still = 0;
  if (f->still >= (uint32_t)FALL_FS * FALL_STILL_MS / 1000) {
    f->window_left = 0;
    f->still = 0;
    return 1;
  }
  return 0;
}

/* Gia tốc lớn nhất từ lần gọi trước, đơn vị 0,1 g (trường peak_acc của gói). */
static inline uint8_t fall_take_peak(fall_t* f) {
  uint32_t v = f->peak_mg / 100;
  f->peak_mg = 0;
  return v > 255 ? 255 : (uint8_t)v;
}

#endif
