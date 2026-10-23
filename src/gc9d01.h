// Minimal GC9D01 (160x160) driver for several panels on one SPI bus.
// Panels can share wires or each have their own (see mirror()); only the
// panel whose CS is low latches anything, so all panels can see the same
// CLK/DIN/DC.
// Stock TFT_eSPI has no GC9D01 driver, so this talks to ESP-IDF's spi_master
// directly: manual CS per panel, manual DC, DMA from internal-RAM buffers.
// Init sequence from Waveshare's 0.71" demo (identical in Arduino_GFX).
#pragma once
#include <Arduino.h>
#include <driver/spi_master.h>

class Gc9d01Bus {
 public:
  static constexpr int kSize = 160;
  static constexpr int kMaxPanels = 2;
  // Largest single pixel transfer (bytes).
  static constexpr int kMaxTransfer = kSize * 2 * 16;

  bool begin(int mosi, int sclk, int dc, int rst, uint32_t hz);
  // Second set of wires for a panel on its own lead. CLK and DIN are copies of
  // the bus signals routed through the GPIO matrix; DC and RST are driven in
  // step with the primary pins. -1 skips a pin. Call after begin().
  void mirror(int mosi2, int sclk2, int dc2, int rst2);
  int addPanel(int csPin);  // returns panel index
  // Hard reset (every RST pin) and init every panel at once (all CS low).
  void initPanels();
  // MADCTL per panel. rot180 uses MX|MY only: no MV, so no even/odd line
  // swap issue in the panel's dual-gate mode.
  void setOrientation(int panel, bool rot180, bool swapRB);

  // Pixel streaming. Buffers must be DMA-capable and hold big-endian RGB565.
  void beginFrame(int panel, int x0, int y0, int x1, int y1);
  void queuePixels(const uint16_t* buf, size_t count);  // async, queue depth 2
  void waitOne();   // wait for the oldest queued transfer
  void endFrame();  // wait for everything, release CS
  int inFlight() const { return inFlight_; }

  void fill(int panel, uint16_t rgb565);  // blocking helper

 private:
  void select(int panel);  // -1 = none, -2 = all
  void command(uint8_t cmd, const uint8_t* data = nullptr, size_t len = 0);
  void window(int x0, int y0, int x1, int y1);
  void setDc(int level);
  void setRst(int level);

  spi_device_handle_t dev_ = nullptr;
  int dc_ = -1, rst_ = -1, dc2_ = -1, rst2_ = -1;
  int cs_[kMaxPanels];
  int numPanels_ = 0;
  spi_transaction_t trans_[2];
  int nextTrans_ = 0;
  int inFlight_ = 0;
};
