/*
  Kiểm tra iomt_packet.h trên máy tính (Linux/WSL có mbedtls):
      gcc -I. test_packet_host.c -lmbedcrypto -o t && ./t
  So từng byte với docs/test_vectors.md (do gateway Python sinh ra).
*/
#include <stdio.h>
#include "iomt_packet.h"

static int same(const char* name, const uint8_t* a, const char* hex, size_t n) {
  uint8_t b[64];
  for (size_t i = 0; i < n; i++) sscanf(hex + 2 * i, "%2hhx", &b[i]);
  int ok = memcmp(a, b, n) == 0;
  printf("%-32s %s\n", name, ok ? "OK" : "SAI");
  return ok;
}

int main(void) {
  int ok = 1;
  uint8_t k[16], nk[16] = {0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
                           0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C};
  memset(k, 0x01, 16);
  uint8_t mic[4], out[32];

  iomt_mic(nk, (const uint8_t*)"", 0, mic);
  ok &= same("CMAC RFC4493 (rong)", mic, "BB1D6929", 4);

  iomt_summary_t s = {0, IOMT_ACT_WALKING, 1234, 120, 110, 52, 45, 17, 13, 87};
  iomt_build_data(out, k, 1, 1, &s, 0);
  ok &= same("DATA fcnt 1", out, "010101000003D204786E342D110D57452F1287", 19);

  s.flags = IOMT_FLAG_FALL; s.peak_acc = 35;
  iomt_build_data(out, k, 1, 2, &s, 1);
  ok &= same("ALARM fcnt 2", out, "020102000103D204786E342D112357E518F8A8", 19);

  iomt_build_hello(out, k, 1, 0xA1B2C3D4, 1);
  ok &= same("HELLO", out, "03010000D4C3B2A1013C57235D", 13);

  const uint8_t ack_buz[] = {0x81, 0x01, 0x02, 0x00, 0x02, 0x05, 0x28, 0x2F, 0x5F, 0xB5};
  iomt_ack_t a;
  int r = iomt_parse_ack(ack_buz, 10, k, 1, 2, &a);
  printf("%-32s %s\n", "ACK BUZZER_ON 5", (r && a.cmd == IOMT_CMD_BUZZER_ON && a.arg == 5) ? "OK" : "SAI");
  ok &= r && a.cmd == IOMT_CMD_BUZZER_ON && a.arg == 5;
  r = iomt_parse_ack(ack_buz, 10, k, 1, 3, &a);          // sai fcnt đang chờ
  printf("%-32s %s\n", "ACK sai fcnt bi bo", r ? "SAI" : "OK");
  ok &= !r;
  uint8_t bad[10];
  memcpy(bad, ack_buz, 10); bad[5] ^= 1;
  r = iomt_parse_ack(bad, 10, k, 1, 2, &a);
  printf("%-32s %s\n", "ACK bi sua bi bo", r ? "SAI" : "OK");
  ok &= !r;

  const uint8_t bc[] = {0x82, 0xFF, 0x03, 0x00, 0xD0, 0x07, 0x0C, 0x05, 0xCE, 0x7A, 0xE6, 0xC8};
  iomt_beacon_t b;
  r = iomt_parse_beacon(bc, 12, nk, &b);
  printf("%-32s %s\n", "BEACON", (r && b.seq == 3 && b.slot_ms == 2000 && b.n_slots == 12) ? "OK" : "SAI");
  ok &= r && b.seq == 3 && b.slot_ms == 2000 && b.n_slots == 12 && b.free_slots == 5;

  const uint8_t poll[] = {0x83, 0x01, 0x07, 0x00, 0x4E, 0x03, 0xD8, 0x45};
  uint16_t seq = 0;
  r = iomt_parse_poll(poll, 8, k, 1, &seq);
  printf("%-32s %s\n", "POLL seq 7", (r && seq == 7) ? "OK" : "SAI");
  ok &= r && seq == 7;

  printf("%-32s %s\n", "iomt_selftest()", iomt_selftest() ? "OK" : "SAI");
  ok &= iomt_selftest();
  printf(ok ? "\nTAT CA KHOP\n" : "\nCO LOI\n");
  return ok ? 0 : 1;
}
