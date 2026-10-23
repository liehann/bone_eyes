#include "gc9d01.h"

#include <driver/gpio.h>
#include <esp_heap_caps.h>
#include <esp_rom_gpio.h>
#include <soc/spi_periph.h>

namespace {

// {cmd, len, data...}; len 0xFF = delay(data[0] * 10 ms) marker; 0x00 cmd ends.
const uint8_t kInit[] = {
    0xFE, 0, 0xEF, 0,
    0x80, 1, 0xFF, 0x81, 1, 0xFF, 0x82, 1, 0xFF, 0x83, 1, 0xFF,
    0x84, 1, 0xFF, 0x85, 1, 0xFF, 0x86, 1, 0xFF, 0x87, 1, 0xFF,
    0x88, 1, 0xFF, 0x89, 1, 0xFF, 0x8A, 1, 0xFF, 0x8B, 1, 0xFF,
    0x8C, 1, 0xFF, 0x8D, 1, 0xFF, 0x8E, 1, 0xFF, 0x8F, 1, 0xFF,
    0x3A, 1, 0x05,  // COLMOD RGB565
    0xEC, 1, 0x01,
    0x74, 7, 0x02, 0x0E, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x98, 1, 0x3E,
    0x99, 1, 0x3E,
    0xB5, 2, 0x0D, 0x0D,
    0x60, 4, 0x38, 0x0F, 0x79, 0x67,
    0x61, 4, 0x38, 0x11, 0x79, 0x67,
    0x64, 6, 0x38, 0x17, 0x71, 0x5F, 0x79, 0x67,
    0x65, 6, 0x38, 0x13, 0x71, 0x5B, 0x79, 0x67,
    0x6A, 2, 0x00, 0x00,
    0x6C, 7, 0x22, 0x02, 0x22, 0x02, 0x22, 0x22, 0x50,
    0x6E, 32, 0x03, 0x03, 0x01, 0x01, 0x00, 0x00, 0x0F, 0x0F, 0x0D, 0x0D, 0x0B, 0x0B, 0x09, 0x09,
              0x00, 0x00, 0x00, 0x00, 0x0A, 0x0A, 0x0C, 0x0C, 0x0E, 0x0E, 0x10, 0x10,
              0x00, 0x00, 0x02, 0x02, 0x04, 0x04,
    0xBF, 1, 0x01,  // dual gate
    0xF9, 1, 0x40,
    0x9B, 1, 0x3B,
    0x93, 3, 0x33, 0x7F, 0x00,
    0x7E, 1, 0x30,
    0x70, 6, 0x0D, 0x02, 0x08, 0x0D, 0x02, 0x08,
    0x71, 3, 0x0D, 0x02, 0x08,
    0x91, 2, 0x0E, 0x09,
    0xC3, 1, 0x19, 0xC4, 1, 0x19, 0xC9, 1, 0x3C,
    0xF0, 6, 0x53, 0x15, 0x0A, 0x04, 0x00, 0x3E,
    0xF2, 6, 0x53, 0x15, 0x0A, 0x04, 0x00, 0x3A,
    0xF1, 6, 0x56, 0xA8, 0x7F, 0x33, 0x34, 0x5F,
    0xF3, 6, 0x52, 0xA4, 0x7F, 0x33, 0x34, 0xDF,
    0x36, 1, 0x00,  // MADCTL (per panel later)
    0x11, 0xFF, 20, // SLPOUT, 200 ms
    0x29, 0xFF, 2,  // DISPON
    0x20, 0,        // INVOFF (reset default; both reference drivers send it)
    0x00,
};

constexpr uint8_t MADCTL_MY = 0x80, MADCTL_MX = 0x40, MADCTL_RGB = 0x08;  // BGR is 0x00 on this panel

}  // namespace

bool Gc9d01Bus::begin(int mosi, int sclk, int dc, int rst, uint32_t hz) {
  mosi_ = mosi;
  sclk_ = sclk;
  dc_ = dc;
  rst_ = rst;
  pinMode(dc_, OUTPUT);
  if (rst_ >= 0) {
    pinMode(rst_, OUTPUT);
    digitalWrite(rst_, HIGH);
  }

  spi_bus_config_t bus = {};
  bus.mosi_io_num = mosi;
  bus.miso_io_num = -1;
  bus.sclk_io_num = sclk;
  bus.quadwp_io_num = -1;
  bus.quadhd_io_num = -1;
  bus.max_transfer_sz = kMaxTransfer;
  if (spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK) return false;
  return addDevice(hz);
}

bool Gc9d01Bus::addDevice(uint32_t hz) {
  spi_device_interface_config_t devcfg = {};
  devcfg.clock_speed_hz = hz;
  devcfg.mode = 0;
  devcfg.spics_io_num = -1;  // CS is per panel, driven by hand
  devcfg.queue_size = 2;
  devcfg.flags = SPI_DEVICE_NO_DUMMY;
  if (spi_bus_add_device(SPI3_HOST, &devcfg, &dev_) != ESP_OK) {
    dev_ = nullptr;
    return false;
  }
  hz_ = hz;
  return true;
}

bool Gc9d01Bus::setClock(uint32_t hz) {
  endFrame();
  if (dev_ && spi_bus_remove_device(dev_) != ESP_OK) return false;
  dev_ = nullptr;
  return addDevice(hz);
}

uint32_t Gc9d01Bus::actualClockHz() const { return spi_get_actual_clock(APB_CLK_FREQ, hz_, 128); }

void Gc9d01Bus::restorePins() {
  // Bus pins go back on the IO_MUX, as spi_bus_initialize() set them.
  if (sclk_ >= 0) gpio_iomux_out(sclk_, spi_periph_signal[SPI3_HOST].func, false);
  if (mosi_ >= 0) gpio_iomux_out(mosi_, spi_periph_signal[SPI3_HOST].func, false);
  routeMirror();
  for (int pin : {dc_, dc2_, rst_, rst2_}) {
    if (pin < 0) continue;
    pinMode(pin, OUTPUT);
    digitalWrite(pin, HIGH);
  }
  for (int i = 0; i < numPanels_; i++) {
    pinMode(cs_[i], OUTPUT);
    digitalWrite(cs_[i], HIGH);
  }
}

void Gc9d01Bus::routeMirror() {
  // The bus pins use the IO_MUX; the same output signals can also be routed
  // through the GPIO matrix to any number of extra pins.
  const int pins[2] = {sclk2_, mosi2_};
  const uint32_t sigs[2] = {spi_periph_signal[SPI3_HOST].spiclk_out, spi_periph_signal[SPI3_HOST].spid_out};
  for (int i = 0; i < 2; i++) {
    if (pins[i] < 0) continue;
    esp_rom_gpio_pad_select_gpio(pins[i]);
    gpio_set_direction((gpio_num_t)pins[i], GPIO_MODE_OUTPUT);
    esp_rom_gpio_connect_out_signal(pins[i], sigs[i], false, false);
  }
}

void Gc9d01Bus::mirror(int mosi2, int sclk2, int dc2, int rst2) {
  sclk2_ = sclk2;
  mosi2_ = mosi2;
  routeMirror();
  dc2_ = dc2;
  if (dc2_ >= 0) {
    pinMode(dc2_, OUTPUT);
    digitalWrite(dc2_, digitalRead(dc_));
  }
  rst2_ = rst2;
  if (rst2_ >= 0) {
    pinMode(rst2_, OUTPUT);
    digitalWrite(rst2_, HIGH);
  }
}

void Gc9d01Bus::setDc(int level) {
  digitalWrite(dc_, level);
  if (dc2_ >= 0) digitalWrite(dc2_, level);
}

void Gc9d01Bus::setRst(int level) {
  if (rst_ >= 0) digitalWrite(rst_, level);
  if (rst2_ >= 0) digitalWrite(rst2_, level);
}

int Gc9d01Bus::addPanel(int csPin) {
  if (numPanels_ >= kMaxPanels) return -1;
  pinMode(csPin, OUTPUT);
  digitalWrite(csPin, HIGH);
  cs_[numPanels_] = csPin;
  return numPanels_++;
}

void Gc9d01Bus::select(int panel) {
  for (int i = 0; i < numPanels_; i++) digitalWrite(cs_[i], (panel == -2 || panel == i) ? LOW : HIGH);
}

void Gc9d01Bus::command(uint8_t cmd, const uint8_t* data, size_t len) {
  spi_transaction_t t = {};
  setDc(LOW);
  t.length = 8;
  t.tx_buffer = &cmd;
  spi_device_polling_transmit(dev_, &t);
  if (len) {
    setDc(HIGH);
    t = {};
    t.length = len * 8;
    t.tx_buffer = data;
    spi_device_polling_transmit(dev_, &t);
  }
}

void Gc9d01Bus::initPanels() {
  const bool hwReset = rst_ >= 0 || rst2_ >= 0;
  if (hwReset) {
    setRst(HIGH);
    delay(5);
    setRst(LOW);
    delay(20);
    setRst(HIGH);
    delay(150);
  }
  select(-2);
  if (!hwReset) {
    command(0x01);  // SWRESET
    delay(150);
  }
  for (const uint8_t* p = kInit; *p;) {
    uint8_t cmd = *p++, len = *p++;
    if (len == 0xFF) {
      command(cmd);
      delay(*p++ * 10);
    } else {
      command(cmd, p, len);
      p += len;
    }
  }
  select(-1);
}

void Gc9d01Bus::setOrientation(int panel, bool rot180, bool swapRB) {
  uint8_t m = (rot180 ? (MADCTL_MX | MADCTL_MY) : 0) | (swapRB ? MADCTL_RGB : 0);
  select(panel);
  command(0x36, &m, 1);
  select(-1);
}

void Gc9d01Bus::window(int x0, int y0, int x1, int y1) {
  uint8_t c[4] = {(uint8_t)(x0 >> 8), (uint8_t)x0, (uint8_t)(x1 >> 8), (uint8_t)x1};
  uint8_t r[4] = {(uint8_t)(y0 >> 8), (uint8_t)y0, (uint8_t)(y1 >> 8), (uint8_t)y1};
  command(0x2A, c, 4);
  command(0x2B, r, 4);
  command(0x2C);
  setDc(HIGH);  // everything after RAMWR is pixel data
}

void Gc9d01Bus::beginFrame(int panel, int x0, int y0, int x1, int y1) {
  endFrame();
  select(panel);
  window(x0, y0, x1, y1);
}

void Gc9d01Bus::queuePixels(const uint16_t* buf, size_t count) {
  if (inFlight_ == 2) waitOne();
  spi_transaction_t& t = trans_[nextTrans_];
  nextTrans_ ^= 1;
  t = {};
  t.length = count * 16;
  t.tx_buffer = buf;
  spi_device_queue_trans(dev_, &t, portMAX_DELAY);
  inFlight_++;
}

void Gc9d01Bus::waitOne() {
  if (!inFlight_) return;
  spi_transaction_t* done;
  spi_device_get_trans_result(dev_, &done, portMAX_DELAY);
  inFlight_--;
}

void Gc9d01Bus::endFrame() {
  while (inFlight_) waitOne();
  select(-1);
}

void Gc9d01Bus::fill(int panel, uint16_t rgb565) {
  constexpr int kRows = 16;
  uint16_t* buf = (uint16_t*)heap_caps_malloc(kSize * kRows * 2, MALLOC_CAP_DMA);
  if (!buf) return;
  uint16_t be = (rgb565 >> 8) | (rgb565 << 8);
  for (int i = 0; i < kSize * kRows; i++) buf[i] = be;
  beginFrame(panel, 0, 0, kSize - 1, kSize - 1);
  for (int y = 0; y < kSize; y += kRows) queuePixels(buf, kSize * kRows);
  endFrame();
  heap_caps_free(buf);
}
