/*
  Cầu nối LoRa cho gateway (ESP32 DevKit + Ra-02 SX1278 433 MHz).

  Cầu nối KHÔNG xử lý gì: nghe LoRa và in từng gói lên USB, nhận lệnh TX từ
  laptop thì phát. Mọi việc kiểm tra MIC, FCnt, ACK, beacon do Python làm.

  Giao thức USB (115200 baud, mỗi dòng kết thúc bằng \n):
    ESP32 -> laptop:  READY <phiên bản> <thông số radio>
                      RX <hex> <rssi> <snr>
                      TXOK
                      TXERR <mã lỗi RadioLib>
                      # <ghi chú>
    laptop -> ESP32:  TX <hex>      phát gói (tối đa 255 byte) rồi nghe tiếp
                      PING          trả lời "# PONG"

  Thư viện: RadioLib (Tools > Manage Libraries). Đã viết theo bản 7.8.1;
  bản 6.x/7.x khác cũng dùng được vì chỉ gọi các hàm cơ bản.
  CHƯA ĐƯỢC BIÊN DỊCH/THỬ TRÊN MẠCH THẬT — lần nạp đầu xem kỹ Serial Monitor.

  !!! LUÔN GẮN ANTEN TRƯỚC KHI CẤP ĐIỆN, phát không anten sẽ hỏng Ra-02 !!!

  Nối dây (đổi hằng số bên dưới nếu nối khác):
    Ra-02   ESP32
    3.3V    3V3        (KHÔNG cắm 5V)
    GND     GND
    NSS     GPIO 5
    SCK     GPIO 18
    MISO    GPIO 19
    MOSI    GPIO 23
    RST     GPIO 14
    DIO0    GPIO 26
*/
#include <RadioLib.h>

// ------------------------------------------------------------ chân
#define PIN_NSS   5
#define PIN_DIO0  26
#define PIN_RST   14

// ------------------------------------------------------------ thông số radio
// PHẢI GIỐNG HỆT trên lót giày và các bộ giả lập E1/E1b (docs/protocol.md mục 1).
#define LORA_FREQ_MHZ   433.0
#define LORA_BW_KHZ     125.0
#define LORA_SF         9
#define LORA_CR         5        // 4/5
#define LORA_SYNC_WORD  0x12     // mạng riêng (không phải LoRaWAN)
#define LORA_POWER_DBM  17
#define LORA_PREAMBLE   8

#define FW_VERSION "lora_bridge 0.1"

SX1278 radio = new Module(PIN_NSS, PIN_DIO0, PIN_RST, RADIOLIB_NC);

volatile bool rxFlag = false;

#if defined(ESP8266) || defined(ESP32)
ICACHE_RAM_ATTR
#endif
void onPacket(void) {
  rxFlag = true;
}

static char lineBuf[600];
static size_t lineLen = 0;
static uint8_t pkt[256];

static void halt(const char* what, int16_t code) {
  while (true) {
    Serial.print("# LOI ");
    Serial.print(what);
    Serial.print(" ma ");
    Serial.println(code);
    delay(2000);
  }
}

static void check(const char* what, int16_t code) {
  if (code != RADIOLIB_ERR_NONE) halt(what, code);
}

static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

static void printHex(const uint8_t* b, size_t n) {
  static const char* H = "0123456789ABCDEF";
  for (size_t i = 0; i < n; i++) {
    Serial.write(H[b[i] >> 4]);
    Serial.write(H[b[i] & 0x0F]);
  }
}

static void startRx() {
  int16_t st = radio.startReceive();
  if (st != RADIOLIB_ERR_NONE) {
    Serial.print("# startReceive loi ");
    Serial.println(st);
  }
}

static void handleRx() {
  rxFlag = false;
  size_t len = radio.getPacketLength();
  float rssi = radio.getRSSI();
  float snr = radio.getSNR();
  if (len > sizeof(pkt)) len = sizeof(pkt);
  int16_t st = radio.readData(pkt, len);
  if (st == RADIOLIB_ERR_NONE) {
    Serial.print("RX ");
    printHex(pkt, len);
    Serial.print(' ');
    Serial.print(rssi, 0);
    Serial.print(' ');
    Serial.println(snr, 1);
  } else {
    Serial.print("# goi hong, ma ");        // CRC sai: bỏ, node sẽ tự gửi lại
    Serial.println(st);
  }
  startRx();                                 // readData đưa module về standby
}

static void handleLine(char* s) {
  if (strncmp(s, "TX ", 3) == 0) {
    const char* h = s + 3;
    size_t hl = strlen(h);
    if (hl == 0 || hl % 2 != 0 || hl / 2 > sizeof(pkt) - 1) {
      Serial.println("TXERR len");
      return;
    }
    size_t n = hl / 2;
    for (size_t i = 0; i < n; i++) {
      int a = hexNibble(h[2 * i]), b = hexNibble(h[2 * i + 1]);
      if (a < 0 || b < 0) {
        Serial.println("TXERR hex");
        return;
      }
      pkt[i] = (uint8_t)((a << 4) | b);
    }
    if (rxFlag) handleRx();                // có gói vừa tới thì in ra trước, kẻo phát đè mất
    int16_t st = radio.transmit(pkt, n);   // chặn tới khi phát xong (~150 ms ở SF9)
    if (st == RADIOLIB_ERR_NONE) {
      Serial.println("TXOK");
    } else {
      Serial.print("TXERR ");
      Serial.println(st);
    }
    rxFlag = false;                        // ngắt DIO0 do TX_DONE, không phải gói nhận
    startRx();
  } else if (strcmp(s, "PING") == 0) {
    Serial.println("# PONG");
  } else if (s[0] != '\0') {
    Serial.print("# lenh la: ");
    Serial.println(s);
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("# khoi dong cau noi LoRa...");

  check("begin", radio.begin());
  check("freq", radio.setFrequency(LORA_FREQ_MHZ));
  check("bw", radio.setBandwidth(LORA_BW_KHZ));
  check("sf", radio.setSpreadingFactor(LORA_SF));
  check("cr", radio.setCodingRate(LORA_CR));
  check("sync", radio.setSyncWord(LORA_SYNC_WORD));
  check("power", radio.setOutputPower(LORA_POWER_DBM));
  check("preamble", radio.setPreambleLength(LORA_PREAMBLE));
  check("crc", radio.setCRC(true));

  radio.setPacketReceivedAction(onPacket);
  startRx();

  Serial.print("READY " FW_VERSION " ");
  Serial.print(LORA_FREQ_MHZ, 1);
  Serial.print("MHz SF");
  Serial.print(LORA_SF);
  Serial.print(" BW");
  Serial.println(LORA_BW_KHZ, 0);
}

void loop() {
  // 1) gói LoRa vừa tới
  if (rxFlag) handleRx();

  // 2) lệnh từ laptop
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      handleLine(lineBuf);
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;                           // dòng quá dài: bỏ
      Serial.println("TXERR line");
    }
  }
}
