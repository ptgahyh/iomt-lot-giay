/* Chạy lot_giay_lora.ino trên máy tính với Arduino/RadioLib giả (thư mục mock/). Xem chay_thu.py. */
#include "Arduino.h"
#include "RadioLib.h"
#include "../lot_giay_lora/lot_giay_lora.ino"

int main() {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  setup();
  for (;;) loop();
}
