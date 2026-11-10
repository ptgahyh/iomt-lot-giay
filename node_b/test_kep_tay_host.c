/*
  Thử phần logic của kẹp tay trên máy tính (không cần ESP32):
    gcc -Wall -Wextra -Ikep_tay_mqtt test_kep_tay_host.c -o t && ./t
  Chạy "./t --in-mau" để in các dòng JSON mẫu (test_kep_tay_gateway.py đưa chúng vào gateway thật).
*/
#include "kep_tay_logic.h"

static int fails = 0, checks = 0;
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("SAI dòng %d: %s\n", __LINE__, #c); } } while (0)

static const char* tele(uint32_t fcnt, int finger, int hrv, int hr, int sv, int spo2, int batt) {
  static char buf[96];
  kt_reading_t r = {fcnt, finger, hrv, hr, sv, spo2, batt};
  if (kt_telemetry_json(buf, sizeof(buf), &r) < 0) return "LOI";
  return buf;
}

int main(int argc, char** argv) {
  if (argc > 1 && !strcmp(argv[1], "--in-mau")) {
    puts(tele(12, 1, 1, 78, 1, 97, 85));
    puts(tele(13, 1, 1, 80, 0, 0, -1));
    puts(tele(14, 0, 1, 80, 1, 97, -1));
    puts(tele(15, 1, 1, 82, 1, 88, -1));
    char a[40];
    kt_ack_json(a, sizeof(a), 3, 1);
    puts(a);
    return 0;
  }

  /* đúng từng ký tự với ví dụ trong docs/protocol.md mục 8 */
  CHECK(!strcmp(tele(12, 1, 1, 78, 1, 97, 85), "{\"fcnt\":12,\"hr\":78,\"spo2\":97,\"finger\":true,\"batt\":85}"));
  /* không đo pin: bỏ batt; spo2 chưa ra: bỏ spo2 */
  CHECK(!strcmp(tele(13, 1, 1, 80, 0, 0, -1), "{\"fcnt\":13,\"hr\":80,\"finger\":true}"));
  /* không có ngón tay: không gửi hr/spo2 dù thuật toán báo hợp lệ */
  CHECK(!strcmp(tele(14, 0, 1, 80, 1, 97, -1), "{\"fcnt\":14,\"finger\":false}"));
  CHECK(!strcmp(tele(4000000000u, 1, 1, 220, 1, 100, 100),
                "{\"fcnt\":4000000000,\"hr\":220,\"spo2\":100,\"finger\":true,\"batt\":100}"));
  /* bộ đệm quá nhỏ thì báo lỗi, không ghi tràn */
  {
    char small[20];
    kt_reading_t r = {12, 1, 1, 78, 1, 97, 85};
    CHECK(kt_telemetry_json(small, sizeof(small), &r) == -1);
  }

  char a[40];
  CHECK(kt_ack_json(a, sizeof(a), 3, 1) > 0 && !strcmp(a, "{\"seq\":3,\"ok\":true}"));
  CHECK(kt_ack_json(a, sizeof(a), 70000, 0) > 0 && !strcmp(a, "{\"seq\":70000,\"ok\":false}"));

  CHECK(!kt_hr_plausible(29) && kt_hr_plausible(30) && kt_hr_plausible(220) && !kt_hr_plausible(221));
  CHECK(!kt_hr_plausible(-999));
  CHECK(!kt_spo2_plausible(69) && kt_spo2_plausible(70) && kt_spo2_plausible(100) && !kt_spo2_plausible(101));

  kt_cmd_t c;
  /* đúng dạng gateway gửi (json.dumps của Python có khoảng trắng) */
  CHECK(kt_parse_cmd("{\"seq\": 3, \"cmd\": \"buzzer_on\", \"arg\": 5}", &c) && c.seq == 3 && c.cmd == KT_CMD_BUZZER_ON && c.arg == 5);
  CHECK(kt_parse_cmd("{\"seq\":4,\"cmd\":\"buzzer_off\",\"arg\":0}", &c) && c.seq == 4 && c.cmd == KT_CMD_BUZZER_OFF && c.arg == 0);
  CHECK(kt_parse_cmd("{\"cmd\": \"set_period\", \"arg\": 10, \"seq\": 65535}", &c) && c.seq == 65535 && c.cmd == KT_CMD_SET_PERIOD && c.arg == 10);
  CHECK(kt_parse_cmd("{\"seq\": 7, \"cmd\": \"blink\"}", &c) && c.cmd == KT_CMD_BLINK && c.arg == 0);
  /* lệnh lạ: vẫn đọc được seq để trả ack ok=false */
  CHECK(kt_parse_cmd("{\"seq\": 8, \"cmd\": \"reboot\", \"arg\": 1}", &c) && c.seq == 8 && c.cmd == KT_CMD_UNKNOWN);
  CHECK(kt_parse_cmd("{\"seq\": 9, \"cmd\": \"buzzer_onx\"}", &c) && c.cmd == KT_CMD_UNKNOWN);
  /* JSON không dùng được */
  CHECK(!kt_parse_cmd("", &c));
  CHECK(!kt_parse_cmd("not json", &c));
  CHECK(!kt_parse_cmd("{\"cmd\": \"blink\"}", &c));
  CHECK(!kt_parse_cmd("{\"seq\": 1}", &c));
  CHECK(!kt_parse_cmd("{\"seq\": \"x\", \"cmd\": \"blink\"}", &c));
  CHECK(!kt_parse_cmd("{\"seq\": 1, \"cmd\": 5}", &c));
  CHECK(!kt_parse_cmd("{\"seq\": 1, \"cmd\": \"blink", &c));

  printf("%d/%d kiểm tra đạt\n", checks - fails, checks);
  return fails ? 1 : 0;
}
