/*
  gait.h - tính đặc trưng dáng đi từ 6 cảm biến lực (FSR), C thuần, không phụ thuộc Arduino.

  Dùng chung cho firmware (lot_giay_lora.ino) và bài thử trên máy tính
  (node_a/test_gait_host.c), nên cùng một đoạn code được kiểm tra ở cả hai nơi.

  Thứ tự 6 kênh (giống mạch BME3 cũ):
    0 gót trái, 1 má trong trái, 2 má ngoài trái, 3 gót phải, 4 má trong phải, 5 má ngoài phải
  Giá trị mỗi kênh là số đọc ADC 12 bit (0..4095), lực càng mạnh số càng lớn.

  Cách dùng:
    gait_t g; gait_init(&g, 200);          // 200 = số mẫu mỗi giây
    gait_sample(&g, v);                    // gọi đều mỗi 5 ms
    gait_report(&g, &r);                   // hết chu kỳ gửi: lấy kết quả và bắt đầu chu kỳ mới
*/
#ifndef IOMT_GAIT_H
#define IOMT_GAIT_H

#include <math.h>
#include <stdint.h>
#include <string.h>

/* Ngưỡng theo thang ADC 12 bit. CẦN CHỈNH LẠI sau khi đo trên mạch thật
   (xem số in ra ở dòng "# F ..." khi đứng, khi nhấc chân). */
#ifndef GAIT_NO_LOAD
#define GAIT_NO_LOAD 300      /* tổng 6 kênh dưới mức này = không ai mang giày */
#endif
#ifndef GAIT_HEEL_ON
#define GAIT_HEEL_ON 1500     /* gót vượt mức này = gót chạm đất */
#endif
#ifndef GAIT_HEEL_OFF
#define GAIT_HEEL_OFF 600     /* gót xuống dưới mức này = gót nhấc lên */
#endif
#define GAIT_STEP_MIN_MS 250  /* hai lần chạm gót của cùng một chân cách nhau ít nhất 250 ms */
#define GAIT_STUCK_HIGH 4090  /* kênh luôn kịch trần cả chu kỳ = nghi chập dây */

typedef struct {
  uint16_t fs;                 /* số mẫu mỗi giây */
  /* cộng dồn trong 1 chu kỳ gửi */
  uint32_t n;                  /* số mẫu */
  uint64_t sum_l, sum_r, sum_heel;
  uint32_t n_loaded;           /* số mẫu có người đứng lên giày */
  uint64_t sum_share, sum_share2;
  uint16_t min_ch[6];
  /* giữ qua các chu kỳ */
  uint16_t steps;              /* cộng dồn từ lúc bật, tự quay vòng 16 bit */
  uint16_t steps_at_start;     /* số bước lúc bắt đầu chu kỳ */
  uint8_t heel_down[2];
  uint32_t since_step[2];      /* số mẫu từ lần chạm gót gần nhất của mỗi chân */
} gait_t;

typedef struct {
  uint8_t activity;            /* 0 chưa rõ, 1 không có lực, 2 đứng, 3 đi (giống IOMT_ACT_*) */
  uint16_t steps;              /* cộng dồn */
  uint16_t steps_in_period;
  uint8_t load_left, load_right;   /* 0..255, chỉ số tương đối */
  uint8_t left_share;          /* % lực dồn lên chân trái, 50 = cân đối */
  uint8_t heel_share;          /* % lực ở gót */
  uint8_t sway;                /* độ lệch chuẩn của left_share trong chu kỳ, đơn vị % */
  uint8_t sensor_fault;        /* 1 nếu có kênh kịch trần suốt chu kỳ */
  uint32_t samples;            /* số mẫu đã dùng, để kiểm tra có đủ 200 mẫu/giây không */
} gait_report_t;

static inline void gait_reset_period(gait_t* g) {
  g->n = 0;
  g->sum_l = g->sum_r = g->sum_heel = 0;
  g->n_loaded = 0;
  g->sum_share = g->sum_share2 = 0;
  for (int i = 0; i < 6; i++) g->min_ch[i] = 0xFFFF;
  g->steps_at_start = g->steps;
}

static inline void gait_init(gait_t* g, uint16_t fs) {
  memset(g, 0, sizeof(*g));
  g->fs = fs ? fs : 200;
  g->since_step[0] = g->since_step[1] = 0xFFFF;
  gait_reset_period(g);
}

static inline void gait_sample(gait_t* g, const uint16_t v[6]) {
  uint32_t l = (uint32_t)v[0] + v[1] + v[2];
  uint32_t r = (uint32_t)v[3] + v[4] + v[5];
  g->n++;
  g->sum_l += l;
  g->sum_r += r;
  g->sum_heel += (uint32_t)v[0] + v[3];
  for (int i = 0; i < 6; i++)
    if (v[i] < g->min_ch[i]) g->min_ch[i] = v[i];

  if (l + r > GAIT_NO_LOAD) {
    uint32_t share = l * 100 / (l + r);
    g->n_loaded++;
    g->sum_share += share;
    g->sum_share2 += share * share;
  }

  /* Đếm bước: mỗi lần gót chạm đất là 1 bước. Có vùng trễ (ON > OFF) và khoảng cách
     tối thiểu để một lần chạm rung không bị đếm thành nhiều bước. */
  uint32_t min_gap = (uint32_t)g->fs * GAIT_STEP_MIN_MS / 1000;
  for (int f = 0; f < 2; f++) {
    uint16_t heel = v[f * 3];
    if (g->since_step[f] < 0xFFFF) g->since_step[f]++;
    if (!g->heel_down[f] && heel > GAIT_HEEL_ON) {
      g->heel_down[f] = 1;
      if (g->since_step[f] >= min_gap) {
        g->steps++;
        g->since_step[f] = 0;
      }
    } else if (g->heel_down[f] && heel < GAIT_HEEL_OFF) {
      g->heel_down[f] = 0;
    }
  }
}

/* Lấy kết quả của chu kỳ vừa qua rồi bắt đầu chu kỳ mới. */
static inline void gait_report(gait_t* g, gait_report_t* out) {
  memset(out, 0, sizeof(*out));
  uint32_t n = g->n ? g->n : 1;
  uint32_t avg_l = (uint32_t)(g->sum_l / n), avg_r = (uint32_t)(g->sum_r / n);
  uint32_t avg_heel = (uint32_t)(g->sum_heel / n);
  uint32_t total = avg_l + avg_r;

  out->samples = g->n;
  out->steps = g->steps;
  out->steps_in_period = (uint16_t)(g->steps - g->steps_at_start);
  if (g->n == 0) out->activity = 0;
  else if (total < GAIT_NO_LOAD) out->activity = 1;
  else if (out->steps_in_period >= 2) out->activity = 3;
  else out->activity = 2;

  uint32_t ll = avg_l * 255 / (3 * 4095), lr = avg_r * 255 / (3 * 4095);
  out->load_left = ll > 255 ? 255 : (uint8_t)ll;
  out->load_right = lr > 255 ? 255 : (uint8_t)lr;
  out->left_share = total > GAIT_NO_LOAD ? (uint8_t)(avg_l * 100 / total) : 50;
  out->heel_share = total > GAIT_NO_LOAD ? (uint8_t)(avg_heel * 100 / total) : 0;
  if (out->heel_share > 100) out->heel_share = 100;

  if (g->n_loaded > 1) {
    double m = (double)g->sum_share / g->n_loaded;
    double var = (double)g->sum_share2 / g->n_loaded - m * m;
    double sd = var > 0 ? sqrt(var) : 0;
    out->sway = sd > 255 ? 255 : (uint8_t)(sd + 0.5);
  }
  if (g->n > 0)
    for (int i = 0; i < 6; i++)
      if (g->min_ch[i] >= GAIT_STUCK_HIGH) out->sensor_fault = 1;

  gait_reset_period(g);
}

#endif
