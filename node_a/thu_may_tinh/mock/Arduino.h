/* Arduino + FreeRTOS giả, đủ để biên dịch lot_giay_lora.ino thành chương trình chạy trên máy tính.
   Chỉ dùng cho bài thử (chay_thu.py), KHÔNG nạp lên mạch. */
#pragma once
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <random>
#include <thread>

#define IRAM_ATTR
#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 2
#define OUTPUT 1
#define ADC_11db 3

inline uint32_t millis() {
  static const auto t0 = std::chrono::steady_clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now() - t0).count();
}
inline void delay(uint32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }

inline std::mt19937& mock_rng() { static std::mt19937 r(std::random_device{}()); return r; }
inline uint32_t esp_random() { return mock_rng()(); }
inline void randomSeed(uint32_t) {}
inline long random(long a, long b) { return b > a ? a + (long)(mock_rng()() % (uint32_t)(b - a)) : a; }
inline long random(long n) { return random(0, n); }

inline int mock_env(const char* k, int def) { const char* v = getenv(k); return v ? atoi(v) : def; }

/* Chân: LED nhớ trạng thái; nút BOOT (chân 0) "được bấm" 150 ms tại giây MOCK_ALARM_AT_S. */
inline int& mock_pin(int p) { static int s[64]; return s[p & 63]; }
inline void pinMode(int, int) {}
inline void digitalWrite(int p, int v) { mock_pin(p) = v; }
inline int digitalRead(int p) {
  if (p == 0) {
    int at = mock_env("MOCK_ALARM_AT_S", -1);
    if (at >= 0) { uint32_t t = millis(); if (t >= (uint32_t)at * 1000 && t < (uint32_t)at * 1000 + 150) return LOW; }
    return HIGH;
  }
  return mock_pin(p);
}

/* ADC: dáng đi giả, mỗi chân 1 bước mỗi 1,2 s, hai chân lệch nhau nửa chu kỳ.
   MOCK_WALK=0 thì đứng yên (lực đều hai chân). */
inline void analogReadResolution(int) {}
inline void analogSetPinAttenuation(int, int) {}
inline int analogRead(int pin) {
  static const int pins[6] = {36, 39, 34, 35, 32, 33};
  int ch = 0;
  for (int i = 0; i < 6; i++) if (pins[i] == pin) ch = i;
  if (!mock_env("MOCK_WALK", 1)) return 1200;
  double t = millis() / 1000.0, ph = fmod(t / 1.2 + (ch >= 3 ? 0.5 : 0.0), 1.0);
  bool stance = ph < 0.6;                       // chân chạm đất 60% chu kỳ
  if (!stance) return 50;
  bool heel = (ch % 3) == 0;
  return heel ? (ph < 0.3 ? 3000 : 400) : (ph < 0.15 ? 300 : 2200);
}

struct MockSerial {
  void begin(long) {}
  void printf(const char* f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); fflush(stdout); }
  void println(const char* s) { puts(s); fflush(stdout); }
  void print(const char* s) { fputs(s, stdout); }
};
static MockSerial Serial;

/* FreeRTOS */
typedef std::mutex* SemaphoreHandle_t;
typedef uint32_t TickType_t;
#define portMAX_DELAY 0xFFFFFFFFu
#define pdMS_TO_TICKS(ms) (ms)
inline SemaphoreHandle_t xSemaphoreCreateMutex() { return new std::mutex(); }
inline int xSemaphoreTake(SemaphoreHandle_t m, uint32_t) { m->lock(); return 1; }
inline int xSemaphoreGive(SemaphoreHandle_t m) { m->unlock(); return 1; }
inline TickType_t xTaskGetTickCount() { return millis(); }
inline void vTaskDelayUntil(TickType_t* last, TickType_t period) {
  *last += period;
  int32_t d = (int32_t)(*last - millis());
  if (d > 0) delay((uint32_t)d);
}
inline int xTaskCreatePinnedToCore(void (*fn)(void*), const char*, int, void* arg, int, void*, int) {
  std::thread(fn, arg).detach();
  return 1;
}
