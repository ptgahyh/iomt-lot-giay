/* RadioLib giả: thay sóng LoRa bằng một cổng TCP nói đúng giao thức USB của ESP32 cầu nối
   (docs/protocol.md mục 7). Gateway thật kết nối vào (port = "socket://127.0.0.1:<cổng>") và
   thấy firmware này như một cầu nối vừa nhận gói của đúng 1 node.
     firmware phát gói   -> gửi gateway dòng "RX <hex> -50 9.0"
     gateway gửi "TX <hex>" -> firmware nhận được gói đó (ACK, BEACON, POLL)
   Cổng lấy từ biến môi trường MOCK_PORT (mặc định 7000). */
#pragma once
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <deque>
#include <string>
#include <vector>
#include "Arduino.h"

#define RADIOLIB_ERR_NONE 0
#define RADIOLIB_NC (-1)

struct Module { Module(int, int, int, int) {} };

class SX1278 {
 public:
  SX1278(Module*) {}
  int16_t begin() {
    int port = mock_env("MOCK_PORT", 7000);
    int srv = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = htons(port);
    if (bind(srv, (sockaddr*)&a, sizeof(a)) != 0 || listen(srv, 1) != 0) return -2;
    std::thread([this, srv] { this->serve(srv); }).detach();
    return 0;
  }
  int16_t setFrequency(double) { return 0; }
  int16_t setBandwidth(double) { return 0; }
  int16_t setSpreadingFactor(int) { return 0; }
  int16_t setCodingRate(int) { return 0; }
  int16_t setSyncWord(int) { return 0; }
  int16_t setOutputPower(int) { return 0; }
  int16_t setPreambleLength(int) { return 0; }
  int16_t setCRC(bool) { return 0; }
  void setPacketReceivedAction(void (*fn)(void)) { action = fn; }
  // Chip thật không nhớ gói cũ: vào chế độ nghe là bộ đệm trống. Gói tới lúc đang phát thì mất.
  int16_t startReceive() {
    std::lock_guard<std::mutex> g(lock);
    q.clear();
    return 0;
  }
  float getRSSI() { return -50; }
  float getSNR() { return 9.0; }

  int16_t transmit(const uint8_t* b, size_t n) {
    delay(mock_env("MOCK_AIRTIME_MS", 52));      // thời gian phát ở SF7
    std::string line = "RX ";
    char h[3];
    for (size_t i = 0; i < n; i++) { snprintf(h, sizeof(h), "%02X", b[i]); line += h; }
    line += " -50 9.0\n";
    std::lock_guard<std::mutex> g(lock);
    if (fd >= 0 && ::send(fd, line.data(), line.size(), MSG_NOSIGNAL) < 0) fd = -1;
    return 0;                                    // chưa có gateway nối vào: gói "bay mất", như sóng thật
  }
  size_t getPacketLength() {
    std::lock_guard<std::mutex> g(lock);
    return q.empty() ? 0 : q.front().size();
  }
  int16_t readData(uint8_t* b, size_t n) {
    std::lock_guard<std::mutex> g(lock);
    if (q.empty()) return -1;
    std::vector<uint8_t> p = q.front();
    q.pop_front();
    memcpy(b, p.data(), n < p.size() ? n : p.size());
    return 0;
  }

 private:
  void (*action)(void) = nullptr;
  std::mutex lock;
  std::deque<std::vector<uint8_t>> q;
  int fd = -1;

  void sendLine(int c, const char* s) { ::send(c, s, strlen(s), MSG_NOSIGNAL); }

  void serve(int srv) {
    for (;;) {
      int c = accept(srv, nullptr, nullptr);
      if (c < 0) continue;
      int one = 1;
      setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
      { std::lock_guard<std::mutex> g(lock); fd = c; }
      sendLine(c, "READY lot_giay_lora-host 433.5MHz SF7 BW125\n");
      std::string buf;
      char tmp[512];
      ssize_t n;
      while ((n = recv(c, tmp, sizeof(tmp), 0)) > 0) {
        buf.append(tmp, n);
        size_t nl;
        while ((nl = buf.find('\n')) != std::string::npos) {
          std::string line = buf.substr(0, nl);
          buf.erase(0, nl + 1);
          if (!line.empty() && line.back() == '\r') line.pop_back();
          if (line.rfind("TX ", 0) == 0) {
            std::vector<uint8_t> p;
            for (size_t i = 3; i + 1 < line.size(); i += 2) p.push_back((uint8_t)strtol(line.substr(i, 2).c_str(), nullptr, 16));
            sendLine(c, "TXOK\n");
            delay(mock_env("MOCK_AIRTIME_MS", 52) * 4 / 5);   // gói gateway phát cũng mất thời gian bay
            { std::lock_guard<std::mutex> g(lock); q.push_back(p); }
            if (action) action();
          } else if (line == "PING") {
            sendLine(c, "# PONG\n");
          }
        }
      }
      { std::lock_guard<std::mutex> g(lock); fd = -1; }
      close(c);
    }
  }
};
