// Line-based serial console. Modules register their own commands.
#pragma once
#include <Arduino.h>

namespace console {

using Handler = void (*)(int argc, char** argv);

void begin();
// name/help must be string literals (stored by pointer).
void add(const char* name, const char* help, Handler fn);
// Call from loop(); dispatches complete lines.
void poll();

// Helpers for handlers.
bool argInt(int argc, char** argv, int i, long& out);
bool argFloat(int argc, char** argv, int i, float& out);

}  // namespace console
