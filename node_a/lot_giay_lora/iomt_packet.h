/*
  iomt_packet.h — đóng gói / kiểm tra gói LoRa phía node (lót giày, E1, E1b).
  Bản C tương ứng với gateway/iomt_gateway/packet.py. Đặc tả: docs/protocol.md.

  Dùng: chép file này vào thư mục sketch của lót giày, #include "iomt_packet.h".
  Cần mbedtls (có sẵn trong core ESP32 cho Arduino, bật CMAC theo mặc định).
  Đã kiểm tra trên máy tính với mbedtls: ra đúng từng byte như docs/test_vectors.md
  (xem node_a/test_packet_host.c). Trên ESP32 hãy chạy lại hàm iomt_selftest().

  Mọi số nhiều byte là little-endian.
*/
#pragma once
#include <stdint.h>
#include <string.h>
#include "mbedtls/cipher.h"
#include "mbedtls/cmac.h"

#define IOMT_DATA    0x01
#define IOMT_ALARM   0x02
#define IOMT_HELLO   0x03
#define IOMT_ACK     0x81
#define IOMT_BEACON  0x82
#define IOMT_POLL    0x83

#define IOMT_FLAG_FALL         0x01
#define IOMT_FLAG_LOW_BATT     0x02
#define IOMT_FLAG_SENSOR_FAULT 0x04
#define IOMT_FLAG_NO_MOTION    0x08
#define IOMT_FLAG_CMD_DONE     0x10

#define IOMT_ACT_UNKNOWN  0
#define IOMT_ACT_NO_LOAD  1
#define IOMT_ACT_STANDING 2
#define IOMT_ACT_WALKING  3

#define IOMT_CMD_NONE       0
#define IOMT_CMD_BUZZER_OFF 1
#define IOMT_CMD_BUZZER_ON  2
#define IOMT_CMD_SET_PERIOD 3
#define IOMT_CMD_LED_BLINK  4

#define IOMT_DATA_LEN   19
#define IOMT_HELLO_LEN  13
#define IOMT_ACK_LEN    10
#define IOMT_BEACON_LEN 12
#define IOMT_POLL_LEN   8

/* Bản tóm tắt 11 byte (DATA và ALARM). Ý nghĩa từng trường: docs/protocol.md mục 3. */
typedef struct {
  uint8_t  flags;
  uint8_t  activity;
  uint16_t steps;        // cộng dồn từ lúc bật, quay vòng
  uint8_t  load_left;    // 0..255 chỉ số tương đối
  uint8_t  load_right;
  uint8_t  left_share;   // % 0..100
  uint8_t  heel_share;   // % 0..100
  uint8_t  sway;
  uint8_t  peak_acc;     // 0,1 g
  uint8_t  battery;      // %
} iomt_summary_t;

typedef struct {
  uint8_t  node_id;
  uint16_t fcnt;
  uint8_t  cmd;
  uint8_t  arg;
} iomt_ack_t;

typedef struct {
  uint16_t seq;
  uint16_t slot_ms;
  uint8_t  n_slots;
  uint8_t  free_slots;
} iomt_beacon_t;

/* MIC = 4 byte đầu của AES-128-CMAC(key, data). Trả 0 nếu thành công. */
static inline int iomt_mic(const uint8_t key[16], const uint8_t* data, size_t len, uint8_t mic[4]) {
  uint8_t full[16];
  const mbedtls_cipher_info_t* info = mbedtls_cipher_info_from_type(MBEDTLS_CIPHER_AES_128_ECB);
  if (info == NULL) return -1;
  int rc = mbedtls_cipher_cmac(info, key, 128, data, len, full);
  if (rc != 0) return rc;
  memcpy(mic, full, 4);
  return 0;
}

static inline int iomt_mic_ok(const uint8_t key[16], const uint8_t* frame, size_t len) {
  uint8_t mic[4];
  if (len < 8 || iomt_mic(key, frame, len - 4, mic) != 0) return 0;
  uint8_t diff = 0;                                   // so sánh không sớm thoát
  for (int i = 0; i < 4; i++) diff |= mic[i] ^ frame[len - 4 + i];
  return diff == 0;
}

static inline void iomt_put16(uint8_t* p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }
static inline uint16_t iomt_get16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }

static inline void iomt_header(uint8_t* out, uint8_t type, uint8_t node_id, uint16_t fcnt) {
  out[0] = type;
  out[1] = node_id;
  iomt_put16(out + 2, fcnt);
}

/* Gói DATA (alarm = 0) hoặc ALARM (alarm = 1), luôn 19 byte. Trả về độ dài, <0 nếu lỗi. */
static inline int iomt_build_data(uint8_t out[IOMT_DATA_LEN], const uint8_t key[16], uint8_t node_id,
                                  uint16_t fcnt, const iomt_summary_t* s, int alarm) {
  iomt_header(out, alarm ? IOMT_ALARM : IOMT_DATA, node_id, fcnt);
  out[4] = s->flags;
  out[5] = s->activity;
  iomt_put16(out + 6, s->steps);
  out[8] = s->load_left;
  out[9] = s->load_right;
  out[10] = s->left_share;
  out[11] = s->heel_share;
  out[12] = s->sway;
  out[13] = s->peak_acc;
  out[14] = s->battery;
  if (iomt_mic(key, out, 15, out + 15) != 0) return -1;
  return IOMT_DATA_LEN;
}

/* HELLO: gửi một lần mỗi khi khởi động, fcnt = 0, nonce = esp_random(). Sau đó DATA đếm từ 1. */
static inline int iomt_build_hello(uint8_t out[IOMT_HELLO_LEN], const uint8_t key[16], uint8_t node_id,
                                   uint32_t boot_nonce, uint8_t fw_version) {
  iomt_header(out, IOMT_HELLO, node_id, 0);
  out[4] = boot_nonce & 0xFF;
  out[5] = (boot_nonce >> 8) & 0xFF;
  out[6] = (boot_nonce >> 16) & 0xFF;
  out[7] = (boot_nonce >> 24) & 0xFF;
  out[8] = fw_version;
  if (iomt_mic(key, out, 9, out + 9) != 0) return -1;
  return IOMT_HELLO_LEN;
}

/* Kiểm tra ACK: đúng độ dài, đúng loại, đúng node, đúng fcnt đang chờ, đúng MIC.
   Trả 1 nếu hợp lệ (điền *ack), 0 nếu không phải ACK dành cho mình. */
static inline int iomt_parse_ack(const uint8_t* fr, size_t len, const uint8_t key[16],
                                 uint8_t my_id, uint16_t expect_fcnt, iomt_ack_t* ack) {
  if (len != IOMT_ACK_LEN || fr[0] != IOMT_ACK || fr[1] != my_id) return 0;
  if (iomt_get16(fr + 2) != expect_fcnt) return 0;
  if (!iomt_mic_ok(key, fr, len)) return 0;
  ack->node_id = fr[1];
  ack->fcnt = expect_fcnt;
  ack->cmd = fr[4];
  ack->arg = fr[5];
  return 1;
}

/* Kiểm tra beacon (ký bằng network key). Trả 1 nếu hợp lệ. */
static inline int iomt_parse_beacon(const uint8_t* fr, size_t len, const uint8_t net_key[16],
                                    iomt_beacon_t* b) {
  if (len != IOMT_BEACON_LEN || fr[0] != IOMT_BEACON || fr[1] != 0xFF) return 0;
  if (!iomt_mic_ok(net_key, fr, len)) return 0;
  b->seq = iomt_get16(fr + 2);
  b->slot_ms = iomt_get16(fr + 4);
  b->n_slots = fr[6];
  b->free_slots = fr[7];
  return 1;
}

/* POLL dành cho mình? (chế độ poll). Trả 1 nếu hợp lệ, *seq = số thứ tự. */
static inline int iomt_parse_poll(const uint8_t* fr, size_t len, const uint8_t key[16],
                                  uint8_t my_id, uint16_t* seq) {
  if (len != IOMT_POLL_LEN || fr[0] != IOMT_POLL || fr[1] != my_id) return 0;
  if (!iomt_mic_ok(key, fr, len)) return 0;
  *seq = iomt_get16(fr + 2);
  return 1;
}

/* Tự kiểm tra: gọi trong setup(), in kết quả ra Serial. Trả 1 nếu khớp docs/test_vectors.md. */
static inline int iomt_selftest(void) {
  uint8_t key[16];
  memset(key, 0x01, 16);
  iomt_summary_t s = {0, IOMT_ACT_WALKING, 1234, 120, 110, 52, 45, 17, 13, 87};
  static const uint8_t expect[IOMT_DATA_LEN] = {
      0x01, 0x01, 0x01, 0x00, 0x00, 0x03, 0xD2, 0x04, 0x78, 0x6E,
      0x34, 0x2D, 0x11, 0x0D, 0x57, 0x45, 0x2F, 0x12, 0x87};
  uint8_t out[IOMT_DATA_LEN];
  if (iomt_build_data(out, key, 1, 1, &s, 0) != IOMT_DATA_LEN) return 0;
  return memcmp(out, expect, IOMT_DATA_LEN) == 0;
}
