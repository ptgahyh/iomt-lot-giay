/*
  Thử gait.h và fall.h trên máy tính bằng tín hiệu giả (không cần mạch):
      gcc -Wall -Wextra -I lot_giay_lora test_gait_host.c -lm -o tg && ./tg
  Tín hiệu giả chỉ kiểm tra công thức chạy đúng. Ngưỡng thật phải chỉnh bằng số đo trên người.
*/
#include <stdio.h>
#include "gait.h"
#include "fall.h"

static int fails = 0;
static void expect(const char* name, int cond, long got) {
  printf("%-52s %s (%ld)\n", name, cond ? "OK" : "SAI", got);
  if (!cond) fails++;
}

/* Đi bộ giả ở fs mẫu/giây: mỗi chân 1 bước mỗi 1,2 s, hai chân lệch nửa chu kỳ.
   left_gain < 1 làm chân trái đạp nhẹ hơn (dáng đi lệch). */
static void walk(gait_t* g, int fs, double seconds, double left_gain) {
  int n = (int)(fs * seconds);
  for (int i = 0; i < n; i++) {
    double t = (double)i / fs;
    uint16_t v[6];
    for (int ch = 0; ch < 6; ch++) {
      double ph = t / 1.2 + (ch >= 3 ? 0.5 : 0.0);
      ph -= (long)ph;
      double x = 50;
      if (ph < 0.6) x = (ch % 3 == 0) ? (ph < 0.3 ? 3000 : 400) : (ph < 0.15 ? 300 : 2200);
      if (ch < 3) x *= left_gain;
      v[ch] = (uint16_t)x;
    }
    gait_sample(g, v);
  }
}

static void constant(gait_t* g, int n, uint16_t l, uint16_t r) {
  uint16_t v[6] = {l, l, l, r, r, r};
  for (int i = 0; i < n; i++) gait_sample(g, v);
}

static int feed(fall_t* f, int n, int32_t x, int32_t y, int32_t z) {
  int hit = 0;
  for (int i = 0; i < n; i++) hit += fall_feed(f, x, y, z);
  return hit;
}

int main(void) {
  gait_t g;
  gait_report_t r;

  /* 1. đi 60 s ở 200 Hz: 50 bước mỗi chân = 100 bước */
  gait_init(&g, 200);
  walk(&g, 200, 60, 1.0);
  gait_report(&g, &r);
  expect("di 60 s, 200 Hz: 100 buoc (+-1)", r.steps >= 99 && r.steps <= 101, r.steps);
  expect("  hoat dong = di (3)", r.activity == 3, r.activity);
  expect("  can doi trai/phai 48..52 %", r.left_share >= 48 && r.left_share <= 52, r.left_share);
  expect("  so mau = 12000", r.samples == 12000, (long)r.samples);
  expect("  khong bao loi cam bien", r.sensor_fault == 0, r.sensor_fault);

  /* 2. cùng tín hiệu ở 50 Hz phải đếm ra cùng số bước (không phụ thuộc tần số lấy mẫu) */
  gait_init(&g, 50);
  walk(&g, 50, 60, 1.0);
  gait_report(&g, &r);
  expect("di 60 s, 50 Hz: 100 buoc (+-1)", r.steps >= 99 && r.steps <= 101, r.steps);

  /* 3. chân trái đạp nhẹ bằng 60%: tỉ lệ chân trái phải tụt rõ dưới 50 */
  gait_init(&g, 200);
  walk(&g, 200, 60, 0.6);
  gait_report(&g, &r);
  expect("chan trai yeu 60%: left_share < 45", r.left_share < 45, r.left_share);

  /* 4. đứng yên, lực đều: không bước, hoạt động = đứng, lắc = 0 */
  gait_init(&g, 200);
  constant(&g, 2000, 1200, 1200);
  gait_report(&g, &r);
  expect("dung yen: 0 buoc", r.steps == 0, r.steps);
  expect("  hoat dong = dung (2)", r.activity == 2, r.activity);
  expect("  left_share = 50", r.left_share == 50, r.left_share);
  expect("  sway = 0", r.sway == 0, r.sway);

  /* 5. không mang giày: hoạt động = không có lực */
  constant(&g, 2000, 10, 10);
  gait_report(&g, &r);
  expect("khong mang giay: hoat dong = 1", r.activity == 1, r.activity);

  /* 6. một kênh kịch trần suốt chu kỳ: báo lỗi cảm biến */
  for (int i = 0; i < 1000; i++) {
    uint16_t v[6] = {4095, 500, 500, 500, 500, 500};
    gait_sample(&g, v);
  }
  gait_report(&g, &r);
  expect("kenh kich tran: sensor_fault = 1", r.sensor_fault == 1, r.sensor_fault);

  /* 7. số bước cộng dồn qua các chu kỳ, steps_in_period chỉ tính chu kỳ này */
  gait_init(&g, 200);
  walk(&g, 200, 12, 1.0);
  gait_report(&g, &r);
  uint16_t first = r.steps;
  walk(&g, 200, 12, 1.0);
  gait_report(&g, &r);
  expect("cong don: buoc tang gap doi (+-2)", r.steps >= 2 * first - 2 && r.steps <= 2 * first + 2, r.steps);
  expect("  steps_in_period ~ 20", r.steps_in_period >= 18 && r.steps_in_period <= 22, r.steps_in_period);

  /* 8. rung khi chạm gót (nảy 3 lần trong 100 ms) chỉ được đếm 1 bước */
  gait_init(&g, 200);
  for (int k = 0; k < 3; k++) {
    constant(&g, 4, 3000, 50);
    constant(&g, 3, 100, 50);
  }
  constant(&g, 100, 3000, 50);
  gait_report(&g, &r);
  expect("got nay 3 lan: chi 1 buoc", r.steps == 1, r.steps);

  /* ---- phát hiện ngã (50 Hz, đơn vị mg) */
  fall_t f;
  fall_init(&f);
  expect("dung yen 10 s: khong bao nga", feed(&f, 500, 0, 0, 1000) == 0, 0);
  /* đi bộ: va đập 1,8 g mỗi nửa giây, không vượt ngưỡng 2,5 g */
  int hit = 0;
  for (int i = 0; i < 20; i++) { hit += feed(&f, 2, 0, 0, 1800); hit += feed(&f, 23, 0, 0, 1000); }
  expect("di bo (dinh 1,8 g): khong bao nga", hit == 0, hit);
  /* nhảy: va đập 3 g rồi tiếp tục cử động mạnh 8 s: không báo */
  hit = feed(&f, 3, 0, 0, 3000);
  for (int i = 0; i < 40; i++) { hit += feed(&f, 5, 0, 0, 1600); hit += feed(&f, 5, 0, 0, 500); }
  expect("va dap roi van cu dong: khong bao nga", hit == 0, hit);
  /* ngã: va đập 3,5 g, lăn 1 s, rồi nằm yên */
  fall_init(&f);
  hit = feed(&f, 3, 2000, 2000, 2000);
  hit += feed(&f, 25, 400, 300, 200);
  hit += feed(&f, 25, 1500, 300, 200);
  hit += feed(&f, 150, 1000, 0, 0);
  expect("va dap + nam yen: bao nga dung 1 lan", hit == 1, hit);
  expect("peak_acc ~ 34 (don vi 0,1 g)", fall_take_peak(&f) >= 33, 34);
  /* nằm yên tiếp 20 s: không báo lại */
  expect("nam yen tiep: khong bao lai", feed(&f, 1000, 1000, 0, 0) == 0, 0);

  printf(fails ? "\nCO %d LOI\n" : "\ntat ca OK\n", fails);
  return fails ? 1 : 0;
}
