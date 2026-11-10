/*
  kep_tay_logic.h - phần không phụ thuộc phần cứng của kẹp tay: tạo JSON gửi đi, đọc JSON lệnh.
  C thuần, dùng chung cho firmware và bài thử trên máy tính (node_b/test_kep_tay_host.c).
  Định dạng: docs/protocol.md mục 8.
*/
#ifndef IOMT_KEP_TAY_LOGIC_H
#define IOMT_KEP_TAY_LOGIC_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  uint32_t fcnt;
  int finger;        /* 1 = có ngón tay */
  int hr_valid, hr;  /* nhịp tim, lần/phút */
  int spo2_valid, spo2;
  int batt;          /* %, <0 = không đo */
} kt_reading_t;

/* {"fcnt":12,"hr":78,"spo2":97,"finger":true,"batt":85}
   Không có ngón tay hoặc thuật toán chưa ra số: bỏ hẳn trường hr/spo2 (gateway chỉ nhận số). */
static inline int kt_telemetry_json(char* out, size_t cap, const kt_reading_t* r) {
  int n = snprintf(out, cap, "{\"fcnt\":%lu", (unsigned long)r->fcnt);
  if (r->finger && r->hr_valid && n < (int)cap) n += snprintf(out + n, cap - n, ",\"hr\":%d", r->hr);
  if (r->finger && r->spo2_valid && n < (int)cap) n += snprintf(out + n, cap - n, ",\"spo2\":%d", r->spo2);
  if (n < (int)cap) n += snprintf(out + n, cap - n, ",\"finger\":%s", r->finger ? "true" : "false");
  if (r->batt >= 0 && n < (int)cap) n += snprintf(out + n, cap - n, ",\"batt\":%d", r->batt);
  if (n < (int)cap) n += snprintf(out + n, cap - n, "}");
  return n < (int)cap ? n : -1;
}

static inline int kt_ack_json(char* out, size_t cap, long seq, int ok) {
  int n = snprintf(out, cap, "{\"seq\":%ld,\"ok\":%s}", seq, ok ? "true" : "false");
  return n < (int)cap ? n : -1;
}

/* Số liệu có hợp lý về sinh lý không (thuật toán của hãng đôi khi ra số vô nghĩa khi ngón tay động). */
static inline int kt_hr_plausible(int hr) { return hr >= 30 && hr <= 220; }
static inline int kt_spo2_plausible(int s) { return s >= 70 && s <= 100; }

enum { KT_CMD_UNKNOWN = 0, KT_CMD_BUZZER_ON, KT_CMD_BUZZER_OFF, KT_CMD_SET_PERIOD, KT_CMD_BLINK };

typedef struct {
  long seq;
  int cmd;
  long arg;
} kt_cmd_t;

/* Tìm "key" trong JSON phẳng, trả con trỏ tới giá trị (sau dấu hai chấm, đã bỏ khoảng trắng). */
static inline const char* kt_find(const char* json, const char* key) {
  char pat[24];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char* p = strstr(json, pat);
  if (!p) return NULL;
  p += strlen(pat);
  while (*p == ' ' || *p == '\t') p++;
  if (*p != ':') return NULL;
  p++;
  while (*p == ' ' || *p == '\t') p++;
  return p;
}

/* Đọc lệnh {"seq": 3, "cmd": "buzzer_on", "arg": 5}. Trả 1 nếu có seq và cmd (cmd lạ vẫn trả 1,
   với cmd = KT_CMD_UNKNOWN, để firmware trả ack ok=false). Trả 0 nếu JSON không dùng được. */
static inline int kt_parse_cmd(const char* json, kt_cmd_t* c) {
  const char* s = kt_find(json, "seq");
  const char* m = kt_find(json, "cmd");
  if (!s || !m || *m != '"') return 0;
  char* end;
  c->seq = strtol(s, &end, 10);
  if (end == s) return 0;
  m++;
  const char* q = strchr(m, '"');
  if (!q) return 0;
  size_t len = (size_t)(q - m);
  c->cmd = KT_CMD_UNKNOWN;
  if (len == 9 && !strncmp(m, "buzzer_on", 9)) c->cmd = KT_CMD_BUZZER_ON;
  else if (len == 10 && !strncmp(m, "buzzer_off", 10)) c->cmd = KT_CMD_BUZZER_OFF;
  else if (len == 10 && !strncmp(m, "set_period", 10)) c->cmd = KT_CMD_SET_PERIOD;
  else if (len == 5 && !strncmp(m, "blink", 5)) c->cmd = KT_CMD_BLINK;
  const char* a = kt_find(json, "arg");
  c->arg = a ? strtol(a, NULL, 10) : 0;
  return 1;
}

#endif
