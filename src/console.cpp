#include "console.h"

#include "config.h"

namespace console {
namespace {

struct Cmd {
  const char* name;
  const char* help;
  Handler fn;
};

constexpr int kMaxCmds = 48;
constexpr int kMaxArgs = 8;
Cmd cmds[kMaxCmds];
int numCmds = 0;
char line[128];
size_t len = 0;

void dispatch(char* s) {
  char* argv[kMaxArgs];
  int argc = 0;
  for (char* tok = strtok(s, " \t"); tok && argc < kMaxArgs; tok = strtok(nullptr, " \t")) {
    argv[argc++] = tok;
  }
  if (argc == 0) return;
  for (int i = 0; i < numCmds; i++) {
    if (strcmp(argv[0], cmds[i].name) == 0) {
      cmds[i].fn(argc, argv);
      return;
    }
  }
  Serial.printf("unknown command '%s' (try 'help')\n", argv[0]);
}

void cmdHelp(int, char**) {
  for (int i = 0; i < numCmds; i++) Serial.printf("  %-8s %s\n", cmds[i].name, cmds[i].help);
}

}  // namespace

void begin() {
  Serial.begin(CONSOLE_BAUD);
  add("help", "list commands", cmdHelp);
}

void add(const char* name, const char* help, Handler fn) {
  if (numCmds < kMaxCmds) cmds[numCmds++] = {name, help, fn};
}

void poll() {
  while (Serial.available()) {
    int c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (len == 0) continue;
      line[len] = 0;
      Serial.printf("> %s\n", line);
      dispatch(line);
      len = 0;
    } else if (c == 8 || c == 127) {
      if (len) len--;
    } else if (len < sizeof(line) - 1) {
      line[len++] = (char)c;
    }
  }
}

bool argInt(int argc, char** argv, int i, long& out) {
  if (i >= argc) return false;
  char* end;
  out = strtol(argv[i], &end, 0);
  return *end == 0;
}

bool argFloat(int argc, char** argv, int i, float& out) {
  if (i >= argc) return false;
  char* end;
  out = strtof(argv[i], &end);
  return *end == 0;
}

}  // namespace console
